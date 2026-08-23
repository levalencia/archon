<script lang="ts">
  import Sidebar from '$lib/components/Sidebar.svelte';
  import TopBar from '$lib/components/TopBar.svelte';
  import ChatMessages from '$lib/components/ChatMessages.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import TracePanel from '$lib/components/TracePanel.svelte';
  import ArtifactPanel from '$lib/components/ArtifactPanel.svelte';

  let messages: any[] = $state([]);
  let isLoading = $state(false);
  let showTrace = $state(false);
  let showSidebar = $state(false);
  let currentConversationId = $state('');
  let traceData = $state({ stats: {}, entries: [], skills: [] });
  let artifacts: any[] = $state([]);
  let selectedArtifact: any = $state(null);

  async function handleSend(msg: string, image?: string) {
    if (!msg.trim() && !image) return;

    // Add user message
    messages = [...messages, { id: Date.now(), role: 'user', content: msg, timestamp: new Date().toLocaleTimeString() }];
    isLoading = true;

    try {
      // Create conversation if needed
      if (!currentConversationId) {
        const convRes = await fetch('/api/conversations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: msg.substring(0, 50) }),
        });
        const conv = await convRes.json();
        currentConversationId = conv.id;
      }

      const body: any = { message: msg, conversation_id: currentConversationId };
      if (image) body.image = image;

      // First: get full response (sync) for tools/skills/artifacts
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        messages = [...messages, { id: Date.now(), role: 'assistant', content: `Error: ${res.status}`, timestamp: new Date().toLocaleTimeString() }];
        return;
      }

      const data = await res.json();

      // Then: stream the response text for visual effect
      const fullResponse = data.response;
      const assistantMsg = {
        id: Date.now(),
        role: 'assistant' as const,
        content: '',
        timestamp: new Date().toLocaleTimeString(),
        thinking_steps: data.thinking_steps,
        tool_calls: data.tool_calls,
        skills_used: data.skills_used,
        sources: data.sources,
        artifacts: data.artifacts,
        iterations: data.iterations,
      };
      messages = [...messages, assistantMsg];

      // Stream text word by word
      const words = fullResponse.split(' ');
      for (let i = 0; i < words.length; i++) {
        assistantMsg.content += (i === 0 ? '' : ' ') + words[i];
        messages = [...messages.slice(0, -1), { ...assistantMsg }];
        if (i % 3 === 0) {
          await new Promise(r => setTimeout(r, 30));
        }
      }

      // Update trace data
      traceData = {
        stats: {
          iterations: data.iterations,
          tools: data.tool_calls?.length || 0,
          tokens: data.tokens_used || 0,
          latency: data.elapsed_ms || 0,
        },
        entries: data.thinking_steps || [],
        skills: data.skills_used || [],
      };

      // Check for artifacts
      if (data.artifacts?.length > 0) {
        artifacts = [...artifacts, ...data.artifacts];
      }

      // (already streamed above)

    } catch (e) {
      messages = [...messages, { id: Date.now(), role: 'assistant', content: `Connection error: ${e}`, timestamp: new Date().toLocaleTimeString() }];
    } finally {
      isLoading = false;
    }
  }

  function handleNewConversation() {
    messages = [];
    currentConversationId = '';
    artifacts = [];
    traceData = { stats: {}, entries: [], skills: [] };
    showSidebar = false;
  }
</script>

<div class="flex h-[100dvh] overflow-hidden bg-[var(--bg-primary)]">
  <!-- Sidebar: hidden on mobile, overlay when toggled -->
  {#if showSidebar}
    <!-- Backdrop -->
    <button
      class="md:hidden fixed inset-0 bg-black/50 z-40 cursor-default"
      onclick={() => showSidebar = false}
    ></button>
  {/if}
  <aside class="
    {showSidebar ? 'translate-x-0' : '-translate-x-full'}
    md:translate-x-0
    fixed md:static z-50
    w-[280px] md:w-[260px]
    h-full
    bg-[var(--bg-secondary)] border-r border-[var(--border)]
    transition-transform duration-200 ease-in-out
    flex flex-col overflow-y-auto
  ">
    <Sidebar
      activeId={currentConversationId}
      onSelect={(id) => { currentConversationId = id; showSidebar = false; }}
      onNew={handleNewConversation}
    />
  </aside>

  <!-- Main content -->
  <div class="flex-1 flex flex-col min-w-0">
    <!-- Top bar with menu button on mobile -->
    <div class="h-[52px] border-b border-[var(--border)] flex items-center px-3 md:px-5 gap-2 bg-[var(--bg-secondary)]">
      <!-- Mobile menu button -->
      <button
        onclick={() => showSidebar = !showSidebar}
        class="md:hidden w-9 h-9 rounded-lg flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] cursor-pointer text-lg"
      >☰</button>

      <!-- Health dot -->
      <div class="w-2 h-2 rounded-full bg-[var(--success)]" title="Healthy"></div>

      <!-- Model -->
      <div class="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-primary)] text-[13px]">
        <div class="w-2 h-2 rounded-full bg-[var(--success)]"></div>
        llama3.1:8b (Ollama)
      </div>

      <div class="flex-1"></div>

      <!-- Nav links (desktop only) -->
      <a href="/documents" class="hidden sm:flex px-3 py-1.5 bg-transparent border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs items-center gap-1 hover:bg-[var(--bg-hover)] no-underline">📄</a>

      <button
        onclick={() => showTrace = !showTrace}
        class="px-3 py-1.5 border rounded-md text-xs cursor-pointer flex items-center gap-1
          {showTrace ? 'bg-[var(--accent-glow)] border-[var(--accent)] text-[var(--accent)]' : 'border-[var(--border)] text-[var(--text-secondary)]'}"
      >🔍</button>

      <a href="/eval" class="hidden sm:flex px-3 py-1.5 bg-transparent border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs items-center gap-1 hover:bg-[var(--bg-hover)] no-underline">🛡️</a>
    </div>

    <!-- Chat area -->
    <div class="flex-1 flex overflow-hidden">
      <div class="flex-1 flex flex-col">
        {#if messages.length === 0}
          <div class="flex-1 flex items-center justify-center p-4">
            <div class="text-center max-w-lg">
              <div class="w-14 h-14 md:w-16 md:h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-2xl md:text-3xl font-bold text-white mx-auto mb-4">A</div>
              <h1 class="text-xl md:text-2xl font-semibold text-[var(--text-primary)] mb-2">Archon</h1>
              <p class="text-sm text-[var(--text-secondary)] mb-6">Production AI agent with tools, skills, and observability.</p>
              <div class="flex gap-2 justify-center flex-wrap">
                {#each ['Calculate sqrt(144) + pi * 2', "What's the current date?", 'Search the web for AI agents'] as prompt}
                  <button
                    onclick={() => handleSend(prompt)}
                    class="px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] transition-all cursor-pointer text-left"
                  >{prompt}</button>
                {/each}
              </div>
            </div>
          </div>
        {:else}
          <ChatMessages {messages} />
        {/if}
        <ChatInput onSend={(msg, img) => handleSend(msg, img)} disabled={isLoading} />
      </div>

      <!-- Trace panel: hidden on mobile unless toggled -->
      {#if showTrace}
        <aside class="
          fixed md:static right-0 top-[52px] bottom-0 z-30
          w-[300px] md:w-[320px]
          bg-[var(--bg-secondary)] border-l border-[var(--border)]
          overflow-y-auto
          shadow-lg md:shadow-none
        ">
          <TracePanel
            stats={traceData.stats}
            entries={traceData.entries}
            skills={traceData.skills}
          />
        </aside>
      {/if}
    </div>
  </div>

  <!-- Artifact panel -->
  {#if artifacts.length > 0}
    <ArtifactPanel {artifacts} />
  {/if}
</div>
