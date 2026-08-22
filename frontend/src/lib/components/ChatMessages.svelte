<script lang="ts">
  import { marked } from 'marked';

  interface ToolCall {
    tool: string;
    status: string;
  }

  interface Source {
    title: string;
    score: number;
    excerpt: string;
  }

  interface ThinkingStep {
    agent: string;
    detail: string;
    done: boolean;
  }

  interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    toolCalls?: ToolCall[];
    sources?: Source[];
    thinkingSteps?: ThinkingStep[];
    iterations?: number;
    tokensUsed?: number;
    piiClean?: boolean;
    grounded?: boolean;
  }

  let { messages = [] }: { messages?: Message[] } = $props();

  function renderMarkdown(text: string): string {
    return marked.parse(text, { async: false }) as string;
  }
</script>

<div class="flex-1 overflow-y-auto py-6">
  {#each messages as msg}
    <div class="max-w-[800px] w-full mx-auto px-6 mb-6">
      <!-- Header -->
      <div class="flex items-center gap-2 mb-2">
        <div class="w-7 h-7 rounded-full flex items-center justify-center text-[13px] font-semibold text-white
          {msg.role === 'user'
            ? 'bg-[var(--accent)]'
            : 'bg-gradient-to-br from-[var(--accent)] to-[var(--purple)]'}">
          {msg.role === 'user' ? 'L' : 'A'}
        </div>
        <span class="text-[13px] font-semibold text-[var(--text-primary)]">
          {msg.role === 'user' ? 'Luis' : 'Archon'}
        </span>
        <span class="text-[11px] text-[var(--text-muted)]">{msg.timestamp}</span>

        {#if msg.role === 'assistant'}
          {#if msg.piiClean}
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[rgba(63,185,80,0.15)] text-[var(--success)]">
              ✓ PII-free
            </span>
          {/if}
          {#if msg.grounded}
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[rgba(63,185,80,0.15)] text-[var(--success)]">
              ✓ Grounded
            </span>
          {/if}
        {/if}
      </div>

      <!-- Thinking panel (assistant only) -->
      {#if msg.role === 'assistant' && msg.thinkingSteps && msg.thinkingSteps.length > 0}
        <div class="ml-9 mb-3 border border-[var(--border)] rounded-[10px] overflow-hidden">
          <div class="px-3 py-2 bg-[var(--bg-tertiary)] flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <span class="text-[var(--success)]">✓</span>
            Reasoning complete — {msg.thinkingSteps.length} steps, {msg.toolCalls?.length ?? 0} tools, {msg.iterations} iterations
          </div>
          <div class="px-3 py-2 border-t border-[var(--border)]">
            {#each msg.thinkingSteps as step}
              <div class="flex items-start gap-2 py-1 text-xs">
                <span class="{step.done ? 'text-[var(--success)]' : 'text-[var(--warning)] animate-pulse-dot'}">
                  {step.done ? '✓' : '●'}
                </span>
                <span class="text-[var(--text-secondary)] font-medium">{step.agent}:</span>
                <span class="text-[var(--text-muted)] font-mono text-[11px]">{step.detail}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Content -->
      <div class="pl-9 text-[15px] leading-[1.7] text-[var(--text-primary)] prose-archon">
        {@html renderMarkdown(msg.content)}
      </div>

      <!-- Sources -->
      {#if msg.sources && msg.sources.length > 0}
        <div class="ml-9 mt-3 flex gap-2 flex-wrap">
          {#each msg.sources as source}
            <div class="px-3 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-xs text-[var(--text-secondary)] flex items-center gap-1.5 cursor-pointer hover:border-[var(--accent)] hover:text-[var(--accent)] transition-all">
              📄 {source.title}
              <span class="text-[var(--success)] font-mono text-[11px]">{source.score.toFixed(2)}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/each}
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
    padding: 16px;
    overflow-x: auto;
    margin: 12px 0;
  }
  :global(.prose-archon pre code) {
    background: none;
    padding: 0;
    color: var(--text-primary);
  }
</style>
