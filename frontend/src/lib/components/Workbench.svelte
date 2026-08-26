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
  let pendingApproval: { tool: string; run_id: string; tool_call_id: string; parameters: Record<string, any> } | null = $state(null);
  let lastOverlayTrigger: HTMLElement | null = null;
  let sidebarOpen = $state(false);
  let inspectorOpen = $state(false);
  let viewportWidth = $state(Number.POSITIVE_INFINITY);
  let sidebarIsModal = $derived(viewportWidth <= 720);
  let inspectorIsModal = $derived(viewportWidth <= 1050);
  let latestAssistant = $derived(messages.findLast((message) => message.role === 'assistant'));

  let controller: AbortController | null = null;
  let logController: AbortController | null = null;

  // ── DOM refs ───────────────────────────────────────────────────────
  let sidebarElement: HTMLElement;
  let sidebarScrim: HTMLButtonElement;
  let mainElement: HTMLElement;
  let inspectorElement: HTMLElement;
  let inspectorScrim: HTMLButtonElement;
  let approvalElement = $state<HTMLElement>();
  let denyButton = $state<HTMLButtonElement>();

  // ── Constants ──────────────────────────────────────────────────────
  const prompts = [
    'Investigate the latest failed run',
    'Evaluate an answer for groundedness',
    'Create a reliability test plan',
  ];

  // ── Lifecycle ──────────────────────────────────────────────────────
  onMount(() => {
    hydrated = true;
    updateViewport();
    window.addEventListener('resize', updateViewport);
    loadHealth();
    connectLogs();
    if (initialId) loadConversation(initialId, false);
    return () => {
      controller?.abort();
      logController?.abort();
      window.removeEventListener('resize', updateViewport);
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
      try {
        const ctx = JSON.parse(payload) as ContextStats;
        context = ctx;
        am.context_stats = ctx;
        // If compaction happened, add it as a visible thinking step
        if (ctx.compacted) {
          am.thinking_steps = [...(am.thinking_steps || []), {
            type: 'compaction',
            detail: `⚡ Context compacted: ${ctx.tokens_before?.toLocaleString()} → ${ctx.tokens_after?.toLocaleString()} tokens (${ctx.saved_pct}% saved, ${ctx.messages_before} → ${ctx.messages_after} messages)`,
            elapsed_ms: am.startedAt ? Math.round(performance.now() - am.startedAt) : 0,
          }];
        }
      } catch { /* skip */ }
    } else if (event.event === 'done') {
      try {
        const d = JSON.parse(payload);
        am.iterations = d.iterations;
        am.elapsed_ms = d.elapsed_ms;
        am.status = 'completed';
        const tokensUsed = d.tokens_used || 0;
        stats = {
          iterations: d.iterations || 0,
          tools: d.tools_used || 0,
          latency: d.elapsed_ms != null ? `${d.elapsed_ms}ms` : '—',
          tokens: tokensUsed ? String(tokensUsed) : '—',
          cost: d.cost_usd != null ? `$${d.cost_usd.toFixed(4)}` : undefined,
        };
        // Populate context from done event if no explicit context event was sent
        if (!context) {
          const budget = 200000;
          context = {
            tokens: tokensUsed,
            budget,
            utilization_pct: Math.round((tokensUsed / budget) * 100),
          };
          am.context_stats = context;
        } else {
          // Update context with output tokens added
          const totalTokens = (context.tokens || 0) + tokensUsed;
          context = {
            ...context,
            tokens: totalTokens,
            utilization_pct: Math.round((totalTokens / (context.budget || 200000)) * 100),
          };
          am.context_stats = context;
        }
      } catch { /* skip */ }
    }

    // Handle human-in-the-loop approval requests
    if (event.event === 'approval_required') {
      try {
        const approval = JSON.parse(payload);
        if (
          typeof approval.tool !== 'string' ||
          typeof approval.run_id !== 'string' || !approval.run_id ||
          typeof approval.tool_call_id !== 'string' || !approval.tool_call_id
        ) {
          pendingApproval = null;
          error = 'Invalid approval request: missing run binding';
          return;
        }
        pendingApproval = approval;
        am.thinking_steps = [...(am.thinking_steps || []), {
          type: 'thinking',
          detail: `⏳ Waiting for approval: ${approval.tool}...`,
          elapsed_ms: elapsed,
        }];
      } catch { /* skip */ }
    }

    // Handle eval scores (auto-quality assessment)
    if (event.event === 'eval') {
      try {
        am.evalScores = JSON.parse(payload);
      } catch { /* skip */ }
    }
    if (event.event === 'verifier' || event.event === 'verification') {
      try { am.verifier = JSON.parse(payload); } catch { /* skip */ }
    }

    messages = [...messages.slice(0, -1), { ...am }];
  }

  // ── Human-in-the-loop approval ─────────────────────────────────────
  async function approve() {
    if (!pendingApproval) return;
    const { tool, run_id, tool_call_id } = pendingApproval;
    try {
      await authenticatedFetch(`/api/chat/approve/${tool_call_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true, run_id }),
      });
      // Add thinking step to the current assistant message
      const am = messages[messages.length - 1];
      if (am && am.role === 'assistant') {
        am.thinking_steps = [...(am.thinking_steps || []), {
          type: 'thinking',
          detail: `✅ Approved: ${tool}`,
          elapsed_ms: am.startedAt ? Math.round(performance.now() - am.startedAt) : 0,
        }];
        messages = [...messages.slice(0, -1), { ...am }];
      }
    } catch (e) {
      console.error('Failed to approve tool call', e);
    } finally {
      pendingApproval = null;
    }
  }

  async function deny() {
    if (!pendingApproval) return;
    const { tool, run_id, tool_call_id } = pendingApproval;
    try {
      await authenticatedFetch(`/api/chat/approve/${tool_call_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: false, run_id }),
      });
      const am = messages[messages.length - 1];
      if (am && am.role === 'assistant') {
        am.thinking_steps = [...(am.thinking_steps || []), {
          type: 'thinking',
          detail: `❌ Denied: ${tool}`,
          elapsed_ms: am.startedAt ? Math.round(performance.now() - am.startedAt) : 0,
        }];
        messages = [...messages.slice(0, -1), { ...am }];
      }
    } catch (e) {
      console.error('Failed to deny tool call', e);
    } finally {
      pendingApproval = null;
    }
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
        status: 'streaming',
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
        const latest = messages.at(-1);
        if (latest?.role === 'assistant') {
          latest.status = 'failed';
          messages = [...messages.slice(0, -1), { ...latest }];
        }
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

  // ── Responsive modal helpers ────────────────────────────────────────
  function updateViewport() {
    const width = window.innerWidth;
    viewportWidth = width;
    // An overlay which becomes a persistent desktop panel is no longer open.
    // This also keeps it closed if the viewport later returns to a breakpoint.
    if (width > 720) sidebarOpen = false;
    if (width > 1050) inspectorOpen = false;
  }

  function setOverlay(element: HTMLElement, scrim: HTMLButtonElement, open: boolean, trigger?: HTMLElement) {
    if (open) lastOverlayTrigger = trigger || document.activeElement as HTMLElement;
    if (element === sidebarElement) {
      sidebarOpen = open && sidebarIsModal;
      if (sidebarOpen) inspectorOpen = false;
    } else {
      inspectorOpen = open && inspectorIsModal;
      if (inspectorOpen) sidebarOpen = false;
    }
    // Scrims are pointer targets only; they must never enter keyboard traversal.
    scrim.tabIndex = -1;
    if (open) requestAnimationFrame(() => getFocusable(element)[0]?.focus());
    else requestAnimationFrame(() => lastOverlayTrigger?.focus());
  }

  function getFocusable(bound: HTMLElement): HTMLElement[] {
    return Array.from(bound.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )).filter((element) => !element.closest('[inert]') && element.getClientRects().length > 0);
  }

  function trapFocus(event: KeyboardEvent, bound: HTMLElement): boolean {
    if (event.key !== 'Tab') return false;
    const focusable = getFocusable(bound);
    if (!focusable.length) {
      event.preventDefault();
      return true;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !bound.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !bound.contains(active))) {
      event.preventDefault();
      first.focus();
    }
    return true;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (pendingApproval && approvalElement) {
      if (trapFocus(event, approvalElement)) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        void deny();
      }
      return;
    }

    const modal = inspectorOpen && inspectorIsModal
      ? inspectorElement
      : sidebarOpen && sidebarIsModal ? sidebarElement : undefined;
    if (modal && trapFocus(event, modal)) return;
    if (event.key !== 'Escape') return;
    if (inspectorOpen) setOverlay(inspectorElement, inspectorScrim, false);
    else if (sidebarOpen) setOverlay(sidebarElement, sidebarScrim, false);
  }

  function safeParameters(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(safeParameters);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      key,
      /secret|token|password|authorization|api[_-]?key|cookie/i.test(key) ? '••••••••' : safeParameters(item),
    ]));
  }

  $effect(() => {
    if (pendingApproval) requestAnimationFrame(() => denyButton?.focus());
  });

  $effect(() => {
    // Read all responsive/modal state before applying it to the bound nodes.
    const approvalOpen = Boolean(pendingApproval);
    const sidebarModalOpen = sidebarIsModal && sidebarOpen;
    const inspectorModalOpen = inspectorIsModal && inspectorOpen;
    if (!sidebarElement || !mainElement || !inspectorElement) return;

    mainElement.toggleAttribute('inert', approvalOpen || sidebarModalOpen || inspectorModalOpen);
    sidebarElement.toggleAttribute(
      'inert',
      approvalOpen || inspectorModalOpen || (sidebarIsModal && !sidebarOpen),
    );
    inspectorElement.toggleAttribute(
      'inert',
      approvalOpen || sidebarModalOpen || (inspectorIsModal && !inspectorOpen),
    );
  });
</script>

<svelte:window onkeydown={handleKeydown} />
<div class="workbench w-full min-w-0">
  <!-- Sidebar overlay -->
  <button
    bind:this={sidebarScrim}
    class:open={sidebarOpen && sidebarIsModal}
    class="scrim"
    aria-label="Close conversations"
    tabindex="-1"
    onclick={() => setOverlay(sidebarElement, sidebarScrim, false)}
  ></button>

  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <aside
    bind:this={sidebarElement}
    data-open={sidebarOpen}
    class:open={sidebarOpen}
    class="sidebar"
    role={sidebarIsModal ? 'dialog' : 'complementary'}
    aria-modal={sidebarIsModal ? 'true' : undefined}
    aria-label="Conversations"
  >
    <Sidebar
      activeId={currentId}
      onSelect={loadConversation}
      onNew={reset}
      onClose={() => setOverlay(sidebarElement, sidebarScrim, false)}
    />
  </aside>

  <!-- Main content area -->
  <main bind:this={mainElement} class="main">
    <header class="topbar">
      <button
        class="icon-button nav-toggle"
        aria-label="Open conversations"
        disabled={!hydrated}
        onclick={(event) => setOverlay(sidebarElement, sidebarScrim, true, event.currentTarget)}
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
        onclick={(event) => setOverlay(inspectorElement, inspectorScrim, true, event.currentTarget)}
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
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <aside
    bind:this={inspectorElement}
    data-open={inspectorOpen}
    class:open={inspectorOpen}
    class="inspector-shell"
    role={inspectorIsModal ? 'dialog' : 'complementary'}
    aria-modal={inspectorIsModal ? 'true' : undefined}
    aria-label="Run inspector"
  >
    <button
      class="sheet-close"
      aria-label="Close inspector"
      onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}
    >×</button>
    <Inspector
      {stats}
      conversationId={currentId}
      onFork={(id) => loadConversation(id)}
      {artifacts}
      {context}
      {logs}
      message={latestAssistant}
      active={activeTab}
      onTab={(t) => activeTab = t}
      onOpenArtifact={() => artifactOpen = true}
      onClearLogs={() => logs = []}
    />
  </aside>

  <button
    bind:this={inspectorScrim}
    class:open={inspectorOpen && inspectorIsModal}
    class="sheet-scrim"
    aria-label="Close inspector"
    tabindex="-1"
    onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}
  ></button>

  {#if pendingApproval}
    <div bind:this={approvalElement} class="approval-backdrop" role="dialog" aria-modal="true" aria-label="Tool approval required">
      <div class="approval-card">
        <div class="approval-header">
          <span class="approval-icon">⚠️</span>
          <h3>Tool Approval Required</h3>
        </div>
        <p class="approval-description">The agent wants to execute the following tool. Please review and approve or deny.</p>
        <div class="approval-detail">
          <span class="approval-detail-label">Tool</span>
          <span class="approval-tool-name">{pendingApproval.tool}</span>
        </div>
        <div class="approval-detail">
          <span class="approval-detail-label">Parameters</span>
          <pre class="approval-params">{JSON.stringify(safeParameters(pendingApproval.parameters), null, 2)}</pre>
        </div>
        <div class="approval-actions">
          <button class="approval-btn approve" onclick={approve}>Approve</button>
          <button bind:this={denyButton} class="approval-btn deny" onclick={deny}>Deny</button>
        </div>
      </div>
    </div>
  {/if}

  {#if artifactOpen}
    <ArtifactPanel {artifacts} onClose={() => artifactOpen = false} />
  {/if}
</div>
