<script lang="ts">
  import Sidebar from '$lib/components/Sidebar.svelte';
  import ChatMessages from '$lib/components/ChatMessages.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import TracePanel from '$lib/components/TracePanel.svelte';
  import ArtifactPanel from '$lib/components/ArtifactPanel.svelte';

  let messages: any[] = $state([]);
  let isLoading = $state(false);
  let showSidebar = $state(false);
  let currentConversationId = $state('');
  let traceData = $state({ stats: {}, entries: [], skills: [] });
  let artifacts: any[] = $state([]);
  let modelName = $state('');
  let showLogs = $state(false);
  let logEntries: any[] = $state([]);
  let logSource: EventSource | null = null;
  let providerName = $state('');

  function connectLogs() {
    if (logSource) logSource.close();
    logSource = new EventSource('/api/logs/stream');
    logSource.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data);
        logEntries = [...logEntries.slice(-150), entry];
        // Auto-scroll
        const panel = document.getElementById('log-panel');
        if (panel) panel.scrollTop = panel.scrollHeight;
      } catch {}
    };
  }

  function toggleLogs() {
    showLogs = !showLogs;
    if (showLogs && !logSource) connectLogs();
  }

  async function loadModelInfo() {
    try {
      const r = await fetch('/api/admin/health');
      if (r.ok) {
        const d = await r.json();
        modelName = d.llm_model || 'claude-opus-4-6';
        providerName = d.llm_provider || 'foundry';
      }
    } catch {
      modelName = 'claude-opus-4-6';
      providerName = 'foundry';
    }
  }
  loadModelInfo();

  async function handleSend(msg: string, image?: string) {
    if (!msg.trim() && !image) return;
    messages = [...messages, { id: Date.now(), role: 'user', content: msg, timestamp: new Date().toLocaleTimeString() }];
    isLoading = true;
    try {
      if (!currentConversationId) {
        const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: msg.substring(0, 50) }) });
        currentConversationId = (await r.json()).id;
      }

      // Create assistant message placeholder
      const am: any = {
        id: Date.now(), role: 'assistant', content: '',
        timestamp: new Date().toLocaleTimeString(),
        thinking_steps: [], tool_calls: [], skills_used: [],
        sources: [], artifacts: [], iterations: 0,
      };
      messages = [...messages, am];

      // SSE streaming request
      const body: any = { message: msg, conversation_id: currentConversationId };
      if (image) body.image = image;

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
        let dataBuffer = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.substring(7).trim();
            dataBuffer = '';
            continue;
          }
          if (line.startsWith('data: ')) {
            dataBuffer += (dataBuffer ? '\n' : '') + line.substring(6);
            continue;
          }
          // Empty line = end of event, process it
          if (line.trim() === '' && currentEvent && dataBuffer) {
            const payload = dataBuffer;
            dataBuffer = '';

          if (currentEvent === 'thinking') {
            am.thinking_steps = [...(am.thinking_steps || []), { type: 'thinking', detail: payload, done: true }];
          } else if (currentEvent === 'skill') {
            try {
              const skill = JSON.parse(payload);
              am.skills_used = [...(am.skills_used || []), skill];
            } catch {}
          } else if (currentEvent === 'tool_call') {
            try {
              const tc = JSON.parse(payload);
              am.tool_calls = [...(am.tool_calls || []), tc];
              am.thinking_steps = [...(am.thinking_steps || []), {
                type: 'tool_call',
                detail: `Called ${tc.tool}(${JSON.stringify(tc.parameters || {}).substring(0, 100)})`,
                done: true,
              }];
            } catch {}
          } else if (currentEvent === 'token') {
            am.content += payload;
          } else if (currentEvent === 'compact') {
            try {
              const compact = JSON.parse(payload);
              am.context_stats = { ...am.context_stats, ...compact, compacted: true };
              am.thinking_steps = [...(am.thinking_steps || []), {
                type: 'compact',
                detail: `Context compacted: ${compact.tokens_before} → ${compact.tokens_after} tokens (${compact.saved_pct}% saved)`,
                done: true,
              }];
            } catch {}
          } else if (currentEvent === 'artifact') {
            try {
              const art = JSON.parse(payload);
              am.artifacts = [...(am.artifacts || []), art];
              artifacts = [...artifacts, art];
            } catch {}
          } else if (currentEvent === 'context') {
            try {
              am.context_stats = JSON.parse(payload);
            } catch {}
          } else if (currentEvent === 'done') {
            try {
              const done = JSON.parse(payload);
              am.iterations = done.iterations;
              traceData = {
                stats: { iterations: done.iterations, tools: done.tools_used || 0, latency: done.elapsed_ms || 0 },
                entries: am.thinking_steps || [],
                skills: done.skills_used || [],
              };
            } catch {}
          }

            currentEvent = '';
          }
          messages = [...messages.slice(0, -1), { ...am }];
        }
      }
    } catch (e) { messages = [...messages, { id: Date.now(), role: 'assistant', content: `Error: ${e}`, timestamp: new Date().toLocaleTimeString() }]; }
    finally { isLoading = false; }
  }

  async function loadConversation(id: string) {
    currentConversationId = id;
    showSidebar = false;
    artifacts = [];
    traceData = { stats: {}, entries: [], skills: [] };

    try {
      const r = await fetch("/api/chat/history/" + id);
      if (r.ok) {
        const data = await r.json();
        const msgs = data.messages || [];
        if (msgs.length > 0) {
          messages = msgs.map((m: any, i: number) => ({
            id: i,
            role: m.role,
            content: m.content,
            timestamp: "",
            thinking_steps: [],
            tool_calls: [],
            skills_used: [],
          }));
        } else {
          messages = [];
        }
      } else {
        messages = [];
      }
    } catch (e) {
      console.error("Failed to load conversation:", e);
      messages = [];
    }
  }

  function handleNewConversation() { messages = []; currentConversationId = ''; artifacts = []; traceData = { stats: {}, entries: [], skills: [] }; showSidebar = false; }
</script>

<!-- 
  LAYOUT: 3 columns fill 100% width, 100% height
  Mobile: chat only + hamburger drawer
  Desktop: sidebar(260px) + chat(flex) + trace(320px) 
-->
<div class="h-[100dvh] w-full flex overflow-hidden bg-[var(--bg-primary)]">

  <!-- ══ COL 1: SIDEBAR ══ -->
  <!-- Mobile: slide-out drawer with backdrop -->
  {#if showSidebar}
    <button class="md:hidden fixed inset-0 bg-black/60 z-40" onclick={() => showSidebar = false}></button>
  {/if}
  <div class="
    {showSidebar ? 'translate-x-0' : '-translate-x-full'}
    md:translate-x-0 md:relative
    fixed z-50 top-0 left-0 bottom-0
    w-[260px] shrink-0
    bg-[var(--bg-secondary)] border-r border-[var(--border)]
    transition-transform duration-200 ease-out
    flex flex-col overflow-y-auto
  ">
    <Sidebar activeId={currentConversationId} onSelect={(id) => loadConversation(id)} onNew={handleNewConversation} />
  </div>

  <!-- ══ COL 2: CENTER (TopBar + Chat + Input) — fills remaining space ══ -->
  <div class="flex-1 flex flex-col min-w-0">
    <!-- TopBar -->
    <header class="h-[48px] border-b border-[var(--border)] flex items-center px-3 md:px-4 gap-2 bg-[var(--bg-secondary)] shrink-0">
      <button onclick={() => showSidebar = !showSidebar} class="md:hidden w-8 h-8 rounded-md flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] cursor-pointer">☰</button>
      <div class="w-2 h-2 rounded-full bg-[var(--success)]"></div>
      <span class="hidden sm:block text-[13px] text-[var(--text-primary)]">{modelName || "loading..."}</span>
      <span class="hidden sm:block text-[11px] text-[var(--text-muted)]">{providerName}</span>
      <button onclick={toggleLogs} class="ml-2 px-2 py-1 text-[10px] rounded {showLogs ? 'bg-[var(--accent)] text-black' : 'bg-[var(--bg-hover)] text-[var(--text-muted)]'} hover:bg-[var(--accent)] hover:text-black cursor-pointer font-mono">LOGS</button>
      <div class="flex-1"></div>
      <a href="/documents" class="hidden md:flex px-2 py-1 rounded text-[var(--text-muted)] text-xs hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] no-underline">📄 Docs</a>
      <a href="/dashboard" class="hidden md:flex px-2 py-1 rounded text-[var(--text-muted)] text-xs hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] no-underline">📊 Metrics</a>
      <a href="/eval" class="hidden md:flex px-2 py-1 rounded text-[var(--text-muted)] text-xs hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] no-underline">🛡️ Security</a>
      <a href="/settings" class="hidden md:flex px-2 py-1 rounded text-[var(--text-muted)] text-xs hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] no-underline">⚙️</a>
    </header>

    <!-- Chat area — fills all available vertical space -->
    {#if messages.length === 0}
      <div class="flex-1 flex items-center justify-center p-4">
        <div class="text-center max-w-md">
          <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-2xl font-bold text-white mx-auto mb-4">A</div>
          <h1 class="text-2xl font-semibold text-[var(--text-primary)] mb-2">Archon</h1>
          <p class="text-sm text-[var(--text-secondary)] mb-6">Production AI agent with tools, skills, and full observability.</p>
          <div class="grid grid-cols-2 gap-2 max-w-sm mx-auto">
            {#each ['Calculate sqrt(144) + pi * 2', "What's the current date?", 'Search the web for AI agents', 'Create an HTML dashboard'] as prompt}
              <button onclick={() => handleSend(prompt)} class="px-3 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] transition-all cursor-pointer text-left">{prompt}</button>
            {/each}
          </div>
        </div>
      </div>
    {:else}
      <ChatMessages {messages} />
    {/if}
    <ChatInput onSend={(msg, img) => handleSend(msg, img)} disabled={isLoading} />
  </div>

  <!-- ══ COL 3: TRACE PANEL — desktop only, fixed width ══ -->
  <div class="hidden lg:flex w-[320px] shrink-0 flex-col bg-[var(--bg-secondary)] border-l border-[var(--border)] overflow-y-auto">
    <TracePanel stats={traceData.stats} entries={traceData.entries} skills={traceData.skills} />
  </div>

  <!-- Artifact overlay -->
  {#if artifacts.length > 0}
    <ArtifactPanel {artifacts} />
  {/if}
</div>
