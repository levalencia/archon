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
  }

  let { messages = [] }: { messages?: Message[] } = $props();

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string;
  }
</script>

<div class="flex-1 overflow-y-auto py-4 md:py-6">
  {#each messages as msg}
    <div class="max-w-[800px] w-full mx-auto px-3 md:px-6 mb-4 md:mb-6">
      <!-- Header -->
      <div class="flex items-center gap-2 mb-2">
        <div class="w-6 h-6 md:w-7 md:h-7 rounded-full flex items-center justify-center text-[12px] md:text-[13px] font-semibold text-white shrink-0
          {msg.role === 'user' ? 'bg-[var(--accent)]' : 'bg-gradient-to-br from-[var(--accent)] to-[var(--purple)]'}">
          {msg.role === 'user' ? 'L' : 'A'}
        </div>
        <span class="text-[13px] font-semibold text-[var(--text-primary)]">
          {msg.role === 'user' ? 'Luis' : 'Archon'}
        </span>
        <span class="text-[11px] text-[var(--text-muted)]">{msg.timestamp}</span>
      </div>

      <!-- THINKING / SKILLS / TOOLS — inline like Claude -->
      {#if msg.role === 'assistant' && (msg.thinking_steps?.length || msg.tool_calls?.length || msg.skills_used?.length)}
        <div class="ml-8 md:ml-9 mb-3 border border-[var(--border)] rounded-xl overflow-hidden">
          <!-- Summary bar -->
          <div class="px-3 py-2 bg-[var(--bg-tertiary)] flex items-center gap-2 text-xs text-[var(--text-secondary)] flex-wrap">
            <span class="text-[var(--success)]">✓</span>
            <span>
              {msg.iterations || 1} iteration{(msg.iterations || 1) > 1 ? 's' : ''}
            </span>
            {#if msg.tool_calls?.length}
              <span class="px-1.5 py-0.5 bg-[rgba(88,166,255,0.15)] text-[var(--accent)] rounded font-mono">
                {msg.tool_calls.length} tool{msg.tool_calls.length > 1 ? 's' : ''}
              </span>
            {/if}
            {#if msg.skills_used?.length}
              <span class="px-1.5 py-0.5 bg-[rgba(188,140,255,0.15)] text-[var(--purple)] rounded font-mono">
                {msg.skills_used.length} skill{msg.skills_used.length > 1 ? 's' : ''}
              </span>
            {/if}
          </div>

          <!-- Skills used -->
          {#if msg.skills_used?.length}
            <div class="px-3 py-2 border-t border-[var(--border)]">
              <div class="text-[11px] text-[var(--text-muted)] mb-1 font-semibold">📚 SKILLS LOADED</div>
              {#each msg.skills_used as skill}
                <div class="flex items-center gap-2 py-0.5 text-xs">
                  <span class="text-[var(--purple)]">●</span>
                  <span class="text-[var(--text-primary)] font-medium">{skill.name}</span>
                  <span class="text-[var(--text-muted)] text-[11px]">{skill.description}</span>
                </div>
              {/each}
            </div>
          {/if}

          <!-- Tool calls -->
          {#if msg.tool_calls?.length}
            <div class="px-3 py-2 border-t border-[var(--border)]">
              <div class="text-[11px] text-[var(--text-muted)] mb-1 font-semibold">🔧 TOOLS EXECUTED</div>
              {#each msg.tool_calls as tc}
                <div class="py-1.5">
                  <div class="flex items-center gap-2 text-xs">
                    <span class="{tc.status === 'success' ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
                      {tc.status === 'success' ? '✓' : '✗'}
                    </span>
                    <span class="text-[var(--accent)] font-mono font-semibold">{tc.tool}</span>
                    <span class="text-[var(--text-muted)] font-mono text-[11px]">
                      ({Object.entries(tc.parameters || {}).map(([k,v]) => `${k}="${v}"`).join(', ')})
                    </span>
                  </div>
                  {#if tc.result}
                    <div class="mt-1 ml-5 px-2 py-1 bg-[var(--bg-primary)] rounded text-[11px] font-mono text-[var(--text-muted)] max-h-16 overflow-hidden">
                      {typeof tc.result === 'string' ? tc.result.substring(0, 200) : JSON.stringify(tc.result).substring(0, 200)}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          {/if}

          <!-- Thinking steps (if any beyond skills/tools) -->
          {#if msg.thinking_steps?.length}
            <div class="px-3 py-2 border-t border-[var(--border)]">
              <div class="text-[11px] text-[var(--text-muted)] mb-1 font-semibold">🧠 REASONING</div>
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

      <!-- Content -->
      <div class="pl-8 md:pl-9 text-[14px] md:text-[15px] leading-[1.7] text-[var(--text-primary)] prose-archon">
        {@html renderMarkdown(msg.content)}
      </div>

      <!-- Sources -->
      {#if msg.sources?.length}
        <div class="ml-8 md:ml-9 mt-3 flex gap-2 flex-wrap">
          {#each msg.sources as source, i}
            <span class="px-2 py-1 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded text-[11px] text-[var(--text-secondary)]">
              [{i+1}] 📄 {source.title} <span class="text-[var(--success)]">{source.score?.toFixed(2)}</span>
            </span>
          {/each}
        </div>
      {/if}

      <!-- Artifacts -->
      {#if msg.artifacts?.length}
        <div class="ml-8 md:ml-9 mt-3 flex gap-2 flex-wrap">
          {#each msg.artifacts as art}
            <span class="px-2 py-1 bg-[rgba(188,140,255,0.1)] border border-[var(--purple)] rounded text-[11px] text-[var(--purple)]">
              🎨 {art.title} ({art.content_length} chars)
            </span>
          {/each}
        </div>
      {/if}
    </div>
  {/each}

  {#if messages.length > 0 && messages[messages.length-1].role === 'user'}
    <div class="max-w-[800px] mx-auto px-3 md:px-6 mb-6">
      <div class="ml-8 md:ml-9 flex items-center gap-2 text-sm text-[var(--text-muted)]">
        <span class="animate-pulse-dot">●</span> Thinking...
      </div>
    </div>
  {/if}
</div>

<style>
  :global(.prose-archon p) { margin-bottom: 12px; }
  :global(.prose-archon strong) { color: var(--text-primary); font-weight: 600; }
  :global(.prose-archon code) {
    background: var(--bg-tertiary);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--accent);
  }
  :global(.prose-archon pre) {
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
    overflow-x: auto;
    margin: 12px 0;
    font-size: 12px;
  }
  :global(.prose-archon pre code) { background: none; padding: 0; color: var(--text-primary); }
  :global(.prose-archon ul), :global(.prose-archon ol) { padding-left: 20px; margin-bottom: 12px; }
  :global(.prose-archon li) { margin-bottom: 4px; }
</style>
