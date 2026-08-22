<script lang="ts">
  import Sidebar from '$lib/components/Sidebar.svelte';
  import TopBar from '$lib/components/TopBar.svelte';
  import ChatMessages from '$lib/components/ChatMessages.svelte';
  import ChatInput from '$lib/components/ChatInput.svelte';
  import TracePanel from '$lib/components/TracePanel.svelte';

  let activeConversationId = $state('1');
  let showTrace = $state(true);
  let isLoading = $state(false);

  let messages = $state([
    {
      id: '1',
      role: 'user' as const,
      content: 'What are the key architecture patterns for production AI agents in 2026?',
      timestamp: '2 min ago',
    },
    {
      id: '2',
      role: 'assistant' as const,
      content: `Based on current research, there are **six key architecture patterns** for production AI agents:

**1. Layered Architecture (6-Layer Stack)**
The O'Reilly "AI Agents Stack" identifies six layers: Model Serving, Tools (MCP), Memory, Orchestration, Eval, and Guardrails.

**2. ReAct Reasoning Loops**
The \`Think → Act → Observe → Repeat\` pattern with **circuit breakers** and **iteration caps**.

**3. Multi-Agent Orchestration**
Coordinator agents delegate to specialists via typed capability contracts.

\`\`\`python
coordinator = AgentCoordinator(
    planner=PlannerAgent(llm),
    retriever=RetrieverAgent(llm),
    validator=ValidatorAgent(llm),
    synthesizer=SynthesizerAgent(llm),
)
\`\`\`

**4. Agentic RAG**
Agent-driven search: decides when, what, and whether results suffice.

**5. Protocol-Based DI**
Python Protocols for vendor-neutral components. Swap providers without changing agent code.

**6. Observability-First**
OpenTelemetry traces with **correlation IDs** linking every step.`,
      timestamp: '1 min ago',
      piiClean: true,
      grounded: true,
      iterations: 4,
      tokensUsed: 1847,
      toolCalls: [
        { tool: 'vector_search', status: 'success' },
        { tool: 'web_search', status: 'success' },
        { tool: 'calculator', status: 'success' },
      ],
      sources: [
        { title: 'research-paper.pdf (p.12)', score: 0.94, excerpt: '' },
        { title: 'research-paper.pdf (p.28)', score: 0.87, excerpt: '' },
        { title: 'research-paper.pdf (p.5)', score: 0.82, excerpt: '' },
      ],
      thinkingSteps: [
        { agent: 'Planner', detail: 'Decomposed into 3 sub-questions', done: true },
        { agent: 'Retriever', detail: 'Searched 12 chunks, found 5 relevant (score > 0.82)', done: true },
        { agent: 'Validator', detail: 'Fact-checked against sources ✓ PII scan clean ✓', done: true },
        { agent: 'Synthesizer', detail: 'Generated answer with 3 citations', done: true },
      ],
    },
  ]);

  let traceData = $state({
    stats: { latency: '1.2s', tokens: '1,847', tools: 3, iterations: 4 },
    correlationId: 'f9d50fdd-c105-4745-a0b8',
    traces: [
      { name: 'LLM: Planning', type: 'llm' as const, meta: ['claude-opus-4-6', '320 tokens', '180ms'], barStart: 0, barWidth: 15 },
      { name: 'Tool: vector_search', type: 'tool' as const, meta: ['pgvector', '12 chunks', '45ms'], barStart: 15, barWidth: 4 },
      { name: 'LLM: Reranking', type: 'llm' as const, meta: ['claude-opus-4-6', '890 tokens', '420ms'], barStart: 19, barWidth: 35 },
      { name: 'Security: PII Scan', type: 'security' as const, meta: ['0 entities', '8ms', 'clean'], barStart: 54, barWidth: 1 },
      { name: 'LLM: Synthesis', type: 'llm' as const, meta: ['claude-opus-4-6', '637 tokens', '540ms'], barStart: 55, barWidth: 45 },
    ],
  });

  async function handleSend(message: string) {
    // Add user message
    const userMsg = {
      id: String(Date.now()),
      role: 'user' as const,
      content: message,
      timestamp: 'Just now',
    };
    messages = [...messages, userMsg];
    isLoading = true;

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          conversation_id: activeConversationId,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        const assistantMsg = {
          id: String(Date.now() + 1),
          role: 'assistant' as const,
          content: data.response,
          timestamp: 'Just now',
          piiClean: true,
          grounded: data.tool_calls?.length > 0,
          iterations: data.iterations,
          tokensUsed: data.tokens_used,
          toolCalls: data.tool_calls || [],
          sources: [],
          thinkingSteps: data.tool_calls?.map((tc: any) => ({
            agent: tc.tool,
            detail: tc.status === 'success' ? 'Completed successfully' : tc.status,
            done: true,
          })) || [],
        };
        messages = [...messages, assistantMsg];

        traceData.stats = {
          latency: '—',
          tokens: String(data.tokens_used),
          tools: data.tool_calls?.length || 0,
          iterations: data.iterations,
        };
        traceData.correlationId = data.correlation_id;
      } else {
        messages = [...messages, {
          id: String(Date.now() + 1),
          role: 'assistant' as const,
          content: 'Sorry, something went wrong. Please try again.',
          timestamp: 'Just now',
        }];
      }
    } catch {
      messages = [...messages, {
        id: String(Date.now() + 1),
        role: 'assistant' as const,
        content: 'Cannot connect to the backend. Make sure `make dev` is running on port 8000.',
        timestamp: 'Just now',
      }];
    } finally {
      isLoading = false;
    }
  }
</script>

<Sidebar activeId={activeConversationId} onSelect={(id) => activeConversationId = id} />

<div class="flex-1 flex flex-col min-w-0">
  <TopBar {showTrace} onToggleTrace={() => showTrace = !showTrace} />

  <div class="flex-1 flex overflow-hidden">
    <div class="flex-1 flex flex-col">
      <ChatMessages {messages} />
      <ChatInput onSend={handleSend} disabled={isLoading} />
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
