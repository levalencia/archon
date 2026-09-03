<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import { CheckCircle2, LoaderCircle, XCircle, ChevronRight, ExternalLink, FileOutput } from 'lucide-svelte';
  import type { Message } from '$lib/types';

  let { messages = [], loading = false, onOpenArtifact = () => {} }: { messages?: Message[]; loading?: boolean; onOpenArtifact?: () => void } = $props();
  let container: HTMLDivElement;
  let now = $state(typeof performance === 'undefined' ? 0 : performance.now());
  let nearBottom = true;

  function protectArtifactHtml(text: string): string {
    const start = text.search(/<(!DOCTYPE\s+html|html[\s>])/i);
    if (start < 0) return text;
    const fencesBefore = text.slice(0, start).match(/```/g)?.length || 0;
    if (fencesBefore % 2 === 1) return text;
    const end = text.toLowerCase().indexOf('</html>', start);
    const stop = end >= 0 ? end + 7 : text.length;
    const html = text.slice(start, stop).replaceAll('```', '``\u200b`');
    return `${text.slice(0, start)}\n\n\`\`\`html\n${html}\n\`\`\`\n${text.slice(stop)}`;
  }
  function markdown(text: string) {
    return DOMPurify.sanitize(marked.parse(protectArtifactHtml(text), { async: false }) as string, { USE_PROFILES: { html: true } });
  }
  $effect(() => { if (!loading) return; const id = setInterval(() => { now = performance.now(); }, 100); return () => clearInterval(id); });
  $effect(() => { messages; requestAnimationFrame(() => { if (container && nearBottom) container.scrollTop = container.scrollHeight; }); });
  function trackScroll() { if (container) nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 120; }
  function fmtMs(ms: number): string { return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`; }
  function elapsed(msg: Message): string { return msg.elapsed_ms != null ? fmtMs(msg.elapsed_ms) : msg.startedAt ? fmtMs(Math.round(now - msg.startedAt)) : '—'; }
  function isStreaming(msg: Message, index: number) { return loading && index === messages.length - 1 && msg.role === 'assistant'; }
  function grounded(msg: Message) {
    const scores = msg.evalScores || [];
    if (!scores.length) return 'Not evaluated';
    const grounding = scores.find((s) => /ground|faith|support/i.test(s.name)) || scores[0];
    return grounding.score >= .7 ? 'Grounded' : 'Needs review';
  }
</script>

<div bind:this={container} onscroll={trackScroll} class="messages" aria-live="polite" data-testid="message-scroll">
  <div class="message-column !w-full !max-w-none px-4 sm:px-6 lg:px-8">
    {#each messages as msg, index}
      <article class:assistant={msg.role === 'assistant'} class="message">
        <div class="avatar" aria-hidden="true">{msg.role === 'assistant' ? 'A' : 'Y'}</div>
        <div class="message-body">
          <header><strong>{msg.role === 'assistant' ? 'Archon' : 'You'}</strong><time>{msg.timestamp}</time></header>
          {#if msg.role === 'assistant'}
            {@const streaming = isStreaming(msg, index)}
            {@const failed = msg.status === 'failed'}
            <div class="mb-3 flex min-h-9 flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-[var(--border)] bg-[rgba(16,21,29,.75)] px-3 py-2 text-[11px] text-[var(--muted)]" aria-label="Execution summary">
              {#if streaming}<LoaderCircle class="animate-spin text-[var(--accent)]" size={14}/><strong class="text-[var(--accent)]">Streaming</strong>
              {:else if failed}<XCircle class="text-[var(--danger)]" size={14}/><strong class="text-[var(--danger)]">Failed</strong>
              {:else}<CheckCircle2 class="text-[var(--accent)]" size={14}/><strong class="text-[var(--text)]">Completed</strong>{/if}
              <span>· {msg.tool_calls?.length || 0} tools</span><span>· {msg.iterations || (streaming ? '…' : 0)} iterations</span><span>· {elapsed(msg)}</span><span class="rounded bg-[var(--raised)] px-1.5 py-0.5 text-[var(--secondary)]">{grounded(msg)}</span>
            </div>
            {#if msg.thinking_steps?.length || msg.tool_calls?.length || msg.skills_used?.length}
              <details class="reasoning" open={streaming && !msg.content}>
                <summary><span class="flex items-center gap-2"><ChevronRight size={14}/> Reasoning and actions</span><span>{(msg.thinking_steps?.length || 0) + (msg.tool_calls?.length || 0)} events</span></summary>
                {#if msg.skills_used?.length}<p class="detail-label">Skills</p>{#each msg.skills_used as skill}<div class="detail-row"><span class="status-dot"></span><strong>{skill.name}</strong><span>{skill.description || ''}</span></div>{/each}{/if}
                {#if msg.tool_calls?.length}<p class="detail-label">Tool calls</p>{#each msg.tool_calls as tool}<div class="detail-row"><span class="status-dot"></span><code>{tool.tool}</code><span>{JSON.stringify(tool.parameters || {})}</span>{#if tool.elapsed_ms != null}<span class="ml-auto whitespace-nowrap font-mono text-[10px] text-[var(--muted)]">{fmtMs(tool.elapsed_ms)}</span>{/if}</div>{/each}{/if}
                {#if msg.thinking_steps?.length}<p class="detail-label">Steps</p>{#each msg.thinking_steps as step}<div class="detail-row"><span class="status-dot"></span><span>{step.detail}</span>{#if step.elapsed_ms != null}<span class="ml-auto whitespace-nowrap font-mono text-[10px] text-[var(--muted)]">{fmtMs(step.elapsed_ms)}</span>{/if}</div>{/each}{/if}
              </details>
            {/if}
            <div class="answer">{@html markdown(msg.content)}</div>
            {#if msg.sources?.length && msg.content}
              <section class="mt-4 rounded-xl border border-[var(--border)] bg-[var(--panel)]" aria-label="Citations">
                <h3 class="m-0 border-b border-[var(--border)] px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-[var(--muted)]">Evidence · {msg.sources.length} sources</h3>
                {#each msg.sources as src, i}<div class="flex min-h-11 items-center gap-2 border-b border-[var(--border)] px-3 text-xs last:border-0"><span class="font-mono font-bold text-[var(--accent)]">S{i + 1}</span>{#if src.url}<a href={src.url} target="_blank" rel="noopener" class="min-w-0 flex-1 truncate text-[var(--text)]">{src.title || src.url}</a><ExternalLink size={13}/>{:else}<span class="min-w-0 flex-1 truncate">{src.title}</span>{/if}{#if src.score != null}<span class="font-mono text-[var(--muted)]">{(src.score * 100).toFixed(0)}%</span>{/if}</div>{/each}
              </section>
            {/if}
            {#if msg.artifacts?.length}<div class="artifact-chips mt-3 flex flex-wrap gap-2">{#each msg.artifacts as art}<button class="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--accent)] bg-[rgba(85,214,190,.08)] px-3 py-1.5 text-xs text-[var(--accent)] transition-colors hover:bg-[rgba(85,214,190,.18)]" onclick={onOpenArtifact}><FileOutput size={14}/> {art.title} · Open preview</button>{/each}</div>{/if}
          {:else}<p class="user-copy">{msg.content}</p>{/if}
        </div>
      </article>
    {/each}
    {#if loading && messages.at(-1)?.role !== 'assistant'}<div class="message assistant"><div class="avatar">A</div><div class="thinking" role="status"><span></span><span></span><span></span> Starting run…</div></div>{/if}
  </div>
</div>
