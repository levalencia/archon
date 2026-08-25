<script lang="ts">
  import { onMount } from 'svelte';

  import Sidebar from '$lib/components/Sidebar.svelte';
  import ChatMessages from '$lib/components/ChatMessages.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import Inspector from '$lib/components/Inspector.svelte';
  import ArtifactPanel from '$lib/components/ArtifactPanel.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';

  import { SSEParser, type SSEEvent } from '$lib/sse';
  import type {
    Artifact,
    ContextStats,
    InspectorTab,
    LogEntry,
    Message,
    RunStats,
  } from '$lib/types';
  import { authenticatedFetch } from '$lib/auth';

  // ── Props ──────────────────────────────────────────────────────────
  let { initialId = '' }: { initialId?: string } = $props();

  // ── State ──────────────────────────────────────────────────────────
  let messages: Message[] = $state([]);
  let artifacts: Artifact[] = $state([]);
  let logs: LogEntry[] = $state([]);
  let context: ContextStats | undefined = $state();
  let currentId = $state('');
  let loading = $state(false);
  let error = $state('');
  let artifactOpen = $state(false);
  let model = $state('Connecting…');
  let provider = $state('');
  let hydrated = $state(false);
  let activeTab: InspectorTab = $state('run');
  let stats: RunStats = $state({ latency: '—', tokens: '—', tools: 0, iterations: 0 });

  let controller: AbortController | null = null;
  let logController: AbortController | null = null;

  // ── DOM refs ───────────────────────────────────────────────────────
  let sidebarElement: HTMLElement;
  let sidebarScrim: HTMLButtonElement;
  let inspectorElement: HTMLElement;
  let inspectorScrim: HTMLButtonElement;

  // ── Constants ──────────────────────────────────────────────────────
  const prompts = [
    'Investigate the latest failed run',
    'Evaluate an answer for groundedness',
    'Create a reliability test plan',
  ];

  // ── Lifecycle ──────────────────────────────────────────────────────
  onMount(() => {
    hydrated = true;
    loadHealth();
    connectLogs();
    if (initialId) loadConversation(initialId, false);
    return () => {
      controller?.abort();
      logController?.abort();
    };
  });

  // ── Health check ───────────────────────────────────────────────────
  async function loadHealth() {
    try {
      const r = await fetch('/healthz');
      if (!r.ok) throw new Error();
      const d = await r.json();
      model = d.llm_model || 'Configured model';
      provider = d.llm_provider || '';
    } catch {
      model = 'Backend unavailable';
      provider = '';
    }
  }

  // ── Log streaming ─────────────────────────────────────────────────
  async function connectLogs() {
    logController = new AbortController();
    try {
      const r = await authenticatedFetch('/api/logs/stream', { signal: logController.signal });
      if (!r.ok || !r.body) return;

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();

      while (true) {
        const { done, value } = await reader.read();
        const text = done ? '' : decoder.decode(value, { stream: true });
        for (const event of parser.push(text, done)) {
          if (event.event === 'message') {
            try {
              logs = [...logs.slice(-249), JSON.parse(event.data)];
            } catch { /* skip malformed */ }
          }
        }
        if (done) break;
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') console.warn('Log stream unavailable');
    }
  }

  // ── Conversation management ────────────────────────────────────────
  function reset() {
    controller?.abort();
    currentId = '';
    messages = [];
    artifacts = [];
    context = undefined;
    stats = { latency: '—', tokens: '—', tools: 0, iterations: 0 };
    error = '';
    setOverlay(sidebarElement, sidebarScrim, false);
    history.replaceState({}, '', '/');
  }

  async function loadConversation(id: string, route = true) {
    controller?.abort();
    currentId = id;
    setOverlay(sidebarElement, sidebarScrim, false);
    error = '';
    loading = true;
    if (route) history.replaceState({}, '', `/chat/${id}`);

    try {
      const r = await authenticatedFetch(`/api/chat/history/${id}`);
      if (!r.ok) throw new Error(`Could not load conversation (${r.status})`);
      const d = await r.json();
      messages = (d.messages || []).map((m: any, i: number) => ({
        id: i,
        role: m.role,
        content: m.content,
        timestamp: '',
      }));
    } catch (e) {
      error = e instanceof Error ? e.message : 'Could not load conversation';
      messages = [];
    } finally {
      loading = false;
    }
  }

  // ── SSE event application ──────────────────────────────────────────
  function apply(event: SSEEvent, am: Message) {
    const payload = event.data;
    const elapsed = am.startedAt ? Math.round(performance.now() - am.startedAt) : 0;

    if (event.event === 'token') {
      am.content += payload;
    } else if (event.event === 'thinking') {
      am.thinking_steps = [...(am.thinking_steps || []), { type: 'thinking', detail: payload, elapsed_ms: elapsed }];
    } else if (event.event === 'skill') {
      try { am.skills_used = [...(am.skills_used || []), JSON.parse(payload)]; } catch { /* skip */ }
    } else if (event.event === 'tool_call') {
      try {
        const tc = JSON.parse(payload);
        tc.elapsed_ms = elapsed;
        am.tool_calls = [...(am.tool_calls || []), tc];
      } catch { /* skip */ }
    } else if (event.event === 'sources') {
      try {
        const srcs = JSON.parse(payload);
        am.sources = [...(am.sources || []), ...srcs];
      } catch { /* skip */ }
    } else if (event.event === 'artifact') {
      try {
        const a = JSON.parse(payload);
        am.artifacts = [...(am.artifacts || []), a];
        artifacts = [...artifacts, a];
      } catch { /* skip */ }
    } else if (event.event === 'context') {
      try { context = JSON.parse(payload); am.context_stats = context; } catch { /* skip */ }
    } else if (event.event === 'done') {
      try {
        const d = JSON.parse(payload);
        am.iterations = d.iterations;
        const tokensUsed = d.tokens_used || 0;
        stats = {
          iterations: d.iterations || 0,
          tools: d.tools_used || 0,
          latency: d.elapsed_ms != null ? `${d.elapsed_ms}ms` : '—',
          tokens: tokensUsed ? String(tokensUsed) : '—',
        };
        // Populate context from done event if no explicit context event was sent
        if (!context) {
          const budget = 200000; // default context length
          context = {
            tokens: tokensUsed,
            budget,
            utilization_pct: Math.round((tokensUsed / budget) * 100),
          };
          am.context_stats = context;
        }
      } catch { /* skip */ }
    }

    messages = [...messages.slice(0, -1), { ...am }];
  }

  // ── Send message ──────────────────────────────────────────────────
  async function send(text: string, image?: string) {
    if (loading) return;
    error = '';
    loading = true;
    controller = new AbortController();

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    messages = [...messages, { id: Date.now(), role: 'user', content: text, timestamp }];

    try {
      // Create conversation if needed
      if (!currentId) {
        const r = await authenticatedFetch('/api/conversations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: text.slice(0, 50) }),
          signal: controller.signal,
        });
        if (!r.ok) throw new Error(`Could not create conversation (${r.status})`);
        currentId = (await r.json()).id;
        // Update URL without navigating (avoids re-mounting the component)
        history.replaceState({}, '', `/chat/${currentId}`);
      }

      // Build assistant message shell
      const am: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: '',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        thinking_steps: [],
        tool_calls: [],
        skills_used: [],
        artifacts: [],
        sources: [],
        startedAt: performance.now(),
      };
      messages = [...messages, am];

      // Stream response
      const r = await authenticatedFetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversation_id: currentId, image: image || '' }),
        signal: controller.signal,
      });
      if (!r.ok || !r.body) throw new Error(`Run failed (${r.status})`);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SSEParser();

      while (true) {
        const { done, value } = await reader.read();
        const chunk = done ? '' : decoder.decode(value, { stream: true });
        for (const event of parser.push(chunk, done)) apply(event, am);
        if (done) break;
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        error = e instanceof Error ? e.message : 'The run failed';
      }
    } finally {
      loading = false;
      controller = null;
    }
  }

  function cancel() {
    controller?.abort();
    loading = false;
  }

  // ── Overlay helpers (mobile only) ───────────────────────────────────
  function isMobile() {
    return window.matchMedia('(max-width: 720px)').matches;
  }

  function setOverlay(element: HTMLElement, scrim: HTMLButtonElement, open: boolean) {
    element.classList.toggle('open', open);
    element.setAttribute('data-open', String(open));
    // Only set inert on mobile — on desktop panels are always interactive
    if (isMobile()) {
      element.toggleAttribute('inert', !open);
    } else {
      element.removeAttribute('inert');
    }
    scrim.classList.toggle('open', open);
    scrim.tabIndex = open ? 0 : -1;
  }
</script>

<div class="workbench">
  <!-- Sidebar overlay -->
  <button
    bind:this={sidebarScrim}
    class="scrim"
    aria-label="Close conversations"
    tabindex="-1"
    onclick={() => setOverlay(sidebarElement, sidebarScrim, false)}
  ></button>

  <aside bind:this={sidebarElement} data-open="false" class="sidebar">
    <Sidebar
      activeId={currentId}
      onSelect={loadConversation}
      onNew={reset}
      onClose={() => setOverlay(sidebarElement, sidebarScrim, false)}
    />
  </aside>

  <!-- Main content area -->
  <main class="main">
    <header class="topbar">
      <button
        class="icon-button nav-toggle"
        aria-label="Open conversations"
        disabled={!hydrated}
        onclick={() => setOverlay(sidebarElement, sidebarScrim, true)}
      >
        <svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
      </button>
      <div class="title">
        <p>Agent Reliability Workbench</p>
        <span>
          <i class:offline={model === 'Backend unavailable'}></i>
          {model} {provider ? `· ${provider}` : ''}
        </span>
      </div>
      <button
        class="mobile-inspector"
        disabled={!hydrated}
        onclick={() => setOverlay(inspectorElement, inspectorScrim, true)}
      >
        Inspect run
      </button>
    </header>

    {#if error}
      <div class="error-banner" role="alert">
        <span>{error}</span>
        <button onclick={() => error = ''}>Dismiss</button>
      </div>
    {/if}

    {#if messages.length === 0}
      <EmptyState {prompts} onSend={send} />
    {:else}
      <ChatMessages {messages} {loading} />
    {/if}

    <ChatInput onSend={send} onCancel={cancel} disabled={false} streaming={loading} />
  </main>

  <!-- Inspector panel -->
  <aside bind:this={inspectorElement} data-open="false" class="inspector-shell">
    <button
      class="sheet-close"
      aria-label="Close inspector"
      onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}
    >×</button>
    <Inspector
      {stats}
      {artifacts}
      {context}
      {logs}
      active={activeTab}
      onTab={(t) => activeTab = t}
      onOpenArtifact={() => artifactOpen = true}
    />
  </aside>

  <button
    bind:this={inspectorScrim}
    class="sheet-scrim"
    aria-label="Close inspector"
    tabindex="-1"
    onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}
  ></button>

  {#if artifactOpen}
    <ArtifactPanel {artifacts} onClose={() => artifactOpen = false} />
  {/if}
</div>
