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

  async function handleSend(msg: string, image?: string) {
    if (!msg.trim() && !image) return;
    messages = [...messages, { id: Date.now(), role: 'user', content: msg, timestamp: new Date().toLocaleTimeString() }];
    isLoading = true;
    try {
      if (!currentConversationId) {
        const r = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: msg.substring(0, 50) }) });
        currentConversationId = (await r.json()).id;
      }
      const body: any = { message: msg, conversation_id: currentConversationId };
      if (image) body.image = image;
      const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) { messages = [...messages, { id: Date.now(), role: 'assistant', content: `Error: ${res.status}`, timestamp: new Date().toLocaleTimeString() }]; return; }
      const data = await res.json();
      traceData = { stats: { iterations: data.iterations, tools: data.tool_calls?.length || 0, tokens: data.tokens_used || 0, latency: data.elapsed_ms || 0 }, entries: data.thinking_steps || [], skills: data.skills_used || [] };
      if (data.artifacts?.length > 0) artifacts = [...artifacts, ...data.artifacts];
      const am: any = { id: Date.now(), role: 'assistant', content: '', timestamp: new Date().toLocaleTimeString(), thinking_steps: data.thinking_steps, tool_calls: data.tool_calls, skills_used: data.skills_used, sources: data.sources, artifacts: data.artifacts, iterations: data.iterations };
      messages = [...messages, am];
      const words = data.response.split(' ');
      for (let i = 0; i < words.length; i++) { am.content += (i === 0 ? '' : ' ') + words[i]; messages = [...messages.slice(0, -1), { ...am }]; if (i % 3 === 0) await new Promise(r => setTimeout(r, 25)); }
    } catch (e) { messages = [...messages, { id: Date.now(), role: 'assistant', content: `Error: ${e}`, timestamp: new Date().toLocaleTimeString() }]; }
    finally { isLoading = false; }
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
    <Sidebar activeId={currentConversationId} onSelect={(id) => { currentConversationId = id; showSidebar = false; }} onNew={handleNewConversation} />
  </div>

  <!-- ══ COL 2: CENTER (TopBar + Chat + Input) — fills remaining space ══ -->
  <div class="flex-1 flex flex-col min-w-0">
    <!-- TopBar -->
    <header class="h-[48px] border-b border-[var(--border)] flex items-center px-3 md:px-4 gap-2 bg-[var(--bg-secondary)] shrink-0">
      <button onclick={() => showSidebar = !showSidebar} class="md:hidden w-8 h-8 rounded-md flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] cursor-pointer">☰</button>
      <div class="w-2 h-2 rounded-full bg-[var(--success)]"></div>
      <span class="hidden sm:block text-[13px] text-[var(--text-primary)]">llama3.1:8b</span>
      <span class="hidden sm:block text-[11px] text-[var(--text-muted)]">Ollama</span>
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
