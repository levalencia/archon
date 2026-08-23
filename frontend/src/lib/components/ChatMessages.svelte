<script lang="ts">
  import { marked } from 'marked';

  interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    thinking_steps?: any[];
    tool_calls?: any[];
    skills_used?: any[];
    sources?: any[];
    artifacts?: any[];
    iterations?: number;
    context_stats?: any;
  }

  let { messages = [] }: { messages?: Message[] } = $props();
  let chatContainer: HTMLDivElement;

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string;
  }

  // Auto-scroll to bottom on new messages
  $effect(() => {
    if (messages.length && chatContainer) {
      requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
      });
    }
  });
</script>

<div bind:this={chatContainer} class="flex-1 overflow-y-auto">
  <div class="max-w-3xl mx-auto px-4 md:px-6 py-4 md:py-8 space-y-6">
    {#each messages as msg}
      <!-- User message -->
      {#if msg.role === 'user'}
        <div class="flex gap-3">
          <div class="w-7 h-7 rounded-full bg-[var(--accent)] flex items-center justify-center text-xs font-bold text-white shrink-0 mt-0.5">L</div>
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline gap-2 mb-1">
              <span class="text-sm font-semibold text-[var(--text-primary)]">Luis</span>
              <span class="text-[11px] text-[var(--text-muted)]">{msg.timestamp}</span>
            </div>
            <p class="text-[15px] leading-relaxed text-[var(--text-primary)]">{msg.content}</p>
          </div>
        </div>

      <!-- Assistant message -->
      {:else}
        <div class="flex gap-3">
          <div class="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-xs font-bold text-white shrink-0 mt-0.5">A</div>
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline gap-2 mb-1">
              <span class="text-sm font-semibold text-[var(--text-primary)]">Archon</span>
              <span class="text-[11px] text-[var(--text-muted)]">{msg.timestamp}</span>
            </div>

            <!-- ═══ REASONING PANEL ═══ -->
            {#if msg.skills_used?.length || msg.tool_calls?.length || msg.thinking_steps?.length}
              <div class="mb-3 rounded-lg border border-[var(--border)] overflow-hidden text-sm">
                <!-- Summary bar -->
                <div class="px-3 py-2 bg-[var(--bg-tertiary)] flex items-center gap-2 flex-wrap">
                  <span class="text-[var(--success)] text-xs">✓</span>
                  <span class="text-xs text-[var(--text-secondary)]">{msg.iterations || 1} iteration{(msg.iterations || 1) > 1 ? 's' : ''}</span>
                  {#if msg.tool_calls?.length}
                    <span class="px-1.5 py-0.5 rounded text-[11px] font-mono bg-[rgba(88,166,255,0.12)] text-[var(--accent)]">
                      🔧 {msg.tool_calls.length} tool{msg.tool_calls.length > 1 ? 's' : ''}
                    </span>
                  {/if}
                  {#if msg.skills_used?.length}
                    <span class="px-1.5 py-0.5 rounded text-[11px] font-mono bg-[rgba(188,140,255,0.12)] text-[var(--purple)]">
                      📚 {msg.skills_used.length} skill{msg.skills_used.length > 1 ? 's' : ''}
                    </span>
                  {/if}
                </div>

                <!-- Skills -->
                {#if msg.skills_used?.length}
                  <div class="px-3 py-2 border-t border-[var(--border)]">
                    {#each msg.skills_used as skill}
                      <div class="flex items-center gap-2 py-0.5">
                        <span class="text-[var(--purple)] text-xs">●</span>
                        <span class="text-xs font-medium text-[var(--text-primary)]">{skill.name}</span>
                        <span class="text-[11px] text-[var(--text-muted)] hidden sm:inline">{skill.description}</span>
                      </div>
                    {/each}
                  </div>
                {/if}

                <!-- Tools -->
                {#if msg.tool_calls?.length}
                  <div class="px-3 py-2 border-t border-[var(--border)]">
                    {#each msg.tool_calls as tc}
                      <div class="py-1">
                        <div class="flex items-center gap-2 text-xs">
                          <span class="{tc.status === 'success' ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
                            {tc.status === 'success' ? '✓' : '✗'}
                          </span>
                          <span class="font-mono font-semibold text-[var(--accent)]">{tc.tool}</span>
                          <span class="font-mono text-[11px] text-[var(--text-muted)] truncate">
                            ({Object.entries(tc.parameters || {}).map(([k,v]) => `${k}="${v}"`).join(', ')})
                          </span>
                        </div>
                        {#if tc.result}
                          <div class="mt-1 ml-5 px-2 py-1 bg-[var(--bg-primary)] rounded text-[11px] font-mono text-[var(--text-muted)] truncate">
                            → {typeof tc.result === 'string' ? tc.result.substring(0, 150) : JSON.stringify(tc.result).substring(0, 150)}
                          </div>
                        {/if}
                      </div>
                    {/each}
                  </div>
                {/if}

                <!-- Reasoning steps -->
                {#if msg.thinking_steps?.length}
                  <div class="px-3 py-2 border-t border-[var(--border)]">
                    {#each msg.thinking_steps as step}
                      <div class="flex items-start gap-2 py-0.5 text-xs">
                        <span class="text-[var(--success)] shrink-0">✓</span>
                        <span class="text-[var(--text-muted)] font-mono text-[11px]">{step.detail}</span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}

            <!-- ═══ CONTEXT BAR ═══ -->
            {#if msg.context_stats}
              {@const ctx = msg.context_stats}
              {@const pct = Math.min(ctx.utilization_pct || 0, 100)}
              <div class="mb-3 px-3 py-2 bg-[var(--bg-tertiary)] rounded-lg">
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-[11px] text-[var(--text-muted)]">Context Window</span>
                  <span class="text-[11px] font-mono text-[var(--text-muted)]">
                    {ctx.tokens?.toLocaleString() || 0} / {ctx.budget?.toLocaleString() || 8000} tokens
                  </span>
                </div>
                <div class="h-2 bg-[var(--bg-primary)] rounded-full overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all duration-500
                      {pct > 75 ? 'bg-[var(--error)]' : pct > 50 ? 'bg-[var(--warning)]' : 'bg-[var(--accent)]'}"
                    style="width: {pct}%"
                  ></div>
                </div>
                {#if ctx.compacted}
                  <div class="mt-1.5 text-[11px] text-[var(--warning)] flex items-center gap-1">
                    ⚡ Context compacted: {ctx.tokens_before?.toLocaleString()} → {ctx.tokens_after?.toLocaleString()} tokens ({ctx.saved_pct}% saved)
                  </div>
                {/if}
              </div>
            {/if}

            <!-- ═══ RESPONSE CONTENT ═══ -->
            <div class="prose-archon text-[15px] leading-relaxed">
              {@html renderMarkdown(msg.content)}
            </div>

            <!-- Sources -->
            {#if msg.sources?.length}
              <div class="mt-3 flex gap-2 flex-wrap">
                {#each msg.sources as source, i}
                  <span class="px-2 py-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-[11px] text-[var(--text-secondary)]">
                    [{i+1}] 📄 {source.title}
                    <span class="text-[var(--success)] font-mono">{source.score?.toFixed(2)}</span>
                  </span>
                {/each}
              </div>
            {/if}

            <!-- Artifacts -->
            {#if msg.artifacts?.length}
              <div class="mt-3 flex gap-2 flex-wrap">
                {#each msg.artifacts as art}
                  <span class="px-2 py-1 bg-[rgba(188,140,255,0.08)] border border-[rgba(188,140,255,0.3)] rounded text-[11px] text-[var(--purple)]">
                    🎨 {art.title} · {art.content_length} chars
                  </span>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {/if}
    {/each}

    <!-- Loading indicator -->
    {#if messages.length > 0 && messages[messages.length-1].role === 'user'}
      <div class="flex gap-3">
        <div class="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-xs font-bold text-white shrink-0">A</div>
        <div class="flex items-center gap-1.5 text-sm text-[var(--text-muted)] py-2">
          <span class="animate-pulse-dot">●</span>
          <span class="animate-pulse-dot" style="animation-delay: 0.2s">●</span>
          <span class="animate-pulse-dot" style="animation-delay: 0.4s">●</span>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  :global(.prose-archon p) { margin-bottom: 0.75rem; }
  :global(.prose-archon strong) { color: var(--text-primary); font-weight: 600; }
  :global(.prose-archon code) {
    background: var(--bg-tertiary); padding: 2px 6px; border-radius: 4px;
    font-family: var(--font-mono); font-size: 13px; color: var(--accent);
  }
  :global(.prose-archon pre) {
    background: var(--bg-tertiary); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 16px; overflow-x: auto; margin: 12px 0;
  }
  :global(.prose-archon pre code) { background: none; padding: 0; color: var(--text-primary); font-size: 13px; }
  :global(.prose-archon ul), :global(.prose-archon ol) { padding-left: 1.25rem; margin-bottom: 0.75rem; }
  :global(.prose-archon li) { margin-bottom: 0.25rem; }
  :global(.prose-archon a) { color: var(--accent); text-decoration: underline; }
  :global(.prose-archon h1, .prose-archon h2, .prose-archon h3) { margin-top: 1.5rem; margin-bottom: 0.5rem; font-weight: 600; }
</style>
