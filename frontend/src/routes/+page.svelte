<script lang="ts">
  import Sidebar from '$lib/components/Sidebar.svelte';
  import TopBar from '$lib/components/TopBar.svelte';
  import ChatMessages from '$lib/components/ChatMessages.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import TracePanel from '$lib/components/TracePanel.svelte';

  let activeConversationId = $state('');
  let showTrace = $state(true);
  let isLoading = $state(false);

  interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    piiClean?: boolean;
    grounded?: boolean;
    iterations?: number;
    tokensUsed?: number;
    toolCalls?: any[];
    sources?: any[];
    thinkingSteps?: any[];
    skillsUsed?: any[];
  }

  let messages: Message[] = $state([]);

  let traceData = $state({
    stats: { latency: '—', tokens: '—', tools: 0, iterations: 0 },
    correlationId: '',
    traces: [] as any[],
  });

  function formatTime(): string {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  async function handleSend(message: string, image?: string) {
    const userMsg: Message = {
      id: String(Date.now()),
      role: 'user',
      content: message,
      timestamp: formatTime(),
    };
    messages = [...messages, userMsg];
    isLoading = true;

    // Add loading message
    const loadingId = String(Date.now() + 1);
    const loadingMsg: Message = {
      id: loadingId,
      role: 'assistant',
      content: '⏳ Thinking...',
      timestamp: formatTime(),
      thinkingSteps: [{ agent: 'Archon', detail: 'Processing your request...', done: false }],
    };
    messages = [...messages, loadingMsg];

    const startTime = performance.now();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          conversation_id: activeConversationId || undefined,
          image: image || '',
        }),
      });

      const elapsed = Math.round(performance.now() - startTime);

      if (response.ok) {
        const data = await response.json();

        if (!activeConversationId) {
          activeConversationId = data.conversation_id;
        }

        // Build thinking steps from real response
        const steps = (data.thinking_steps || []).map((s: any) => ({
          agent: s.agent || 'Archon',
          detail: s.detail || '',
          done: true,
        }));

        const assistantMsg: Message = {
          id: loadingId,
          role: 'assistant',
          content: data.response,
          timestamp: formatTime(),
          piiClean: true,
          grounded: (data.tool_calls?.length || 0) > 0,
          iterations: data.iterations,
          tokensUsed: data.tokens_used,
          toolCalls: data.tool_calls || [],
          thinkingSteps: steps,
          skillsUsed: data.skills_used || [],
        };

        // Replace loading message
        messages = messages.map(m => m.id === loadingId ? assistantMsg : m);

        // Update trace panel
        const traces = [];
        for (const step of data.thinking_steps || []) {
          if (step.type === 'skills') {
            traces.push({
              name: `Skills: ${step.detail}`,
              type: 'security' as const,
              meta: [step.detail],
              barStart: 0,
              barWidth: 5,
            });
          } else if (step.type === 'tool_call') {
            traces.push({
              name: `Tool: ${step.detail}`,
              type: 'tool' as const,
              meta: [step.detail],
              barStart: traces.length * 15,
              barWidth: 15,
            });
          } else {
            traces.push({
              name: `LLM: ${step.agent}`,
              type: 'llm' as const,
              meta: [step.detail],
              barStart: traces.length * 15,
              barWidth: 30,
            });
          }
        }

        traceData = {
          stats: {
            latency: `${elapsed}ms`,
            tokens: String(data.tokens_used || 0),
            tools: data.tool_calls?.length || 0,
            iterations: data.iterations || 1,
          },
          correlationId: data.correlation_id || '',
          traces,
        };
      } else {
        messages = messages.map(m =>
          m.id === loadingId
            ? { ...m, content: `Error: ${response.status} ${response.statusText}`, thinkingSteps: [] }
            : m
        );
      }
    } catch (err) {
      messages = messages.map(m =>
        m.id === loadingId
          ? {
              ...m,
              content: 'Cannot connect to backend. Run `make dev` in the backend directory.',
              thinkingSteps: [],
            }
          : m
      );
    } finally {
      isLoading = false;
    }
  }

  function handleNewConversation() {
    messages = [];
    activeConversationId = '';
    traceData = { stats: { latency: '—', tokens: '—', tools: 0, iterations: 0 }, correlationId: '', traces: [] };
  }
</script>

<Sidebar activeId={activeConversationId} onSelect={(id) => activeConversationId = id} onNew={handleNewConversation} />

<div class="flex-1 flex flex-col min-w-0">
  <TopBar {showTrace} onToggleTrace={() => showTrace = !showTrace} />

  <div class="flex-1 flex overflow-hidden">
    <div class="flex-1 flex flex-col">
      {#if messages.length === 0}
        <!-- Empty state -->
        <div class="flex-1 flex items-center justify-center">
          <div class="text-center">
            <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-3xl font-bold text-white mx-auto mb-4">
              A
            </div>
            <h1 class="text-2xl font-semibold text-[var(--text-primary)] mb-2">Archon</h1>
            <p class="text-[var(--text-secondary)] mb-6 max-w-md">
              Production AI agent with ReAct reasoning, multi-agent orchestration,
              RAG, guardrails, and full observability.
            </p>
            <div class="flex gap-3 justify-center flex-wrap max-w-lg">
              {#each ['What architecture patterns do AI agents use?', 'Calculate sqrt(144) + pi * 2', "What's the current date and time?", 'Search the web for SvelteKit tutorials'] as prompt}
                <button
                  onclick={() => handleSend(prompt)}
                  class="px-4 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)] transition-all cursor-pointer text-left"
                >
                  {prompt}
                </button>
              {/each}
            </div>
          </div>
        </div>
      {:else}
        <ChatMessages {messages} />
      {/if}
      <ChatInput onSend={(msg, img) => handleSend(msg, img)} disabled={isLoading} />
    </div>

    {#if showTrace}
      <TracePanel
        stats={traceData.stats}
        correlationId={traceData.correlationId}
        traces={traceData.traces}
      />
    {/if}
  </div>
</div>
