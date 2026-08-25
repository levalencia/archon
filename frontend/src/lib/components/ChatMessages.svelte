<script lang="ts">
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';
  import type { Message } from '$lib/types';

  let { messages = [], loading = false }: { messages?: Message[]; loading?: boolean } = $props();
  let container: HTMLDivElement;
  let now = $state(performance.now());

  function markdown(text: string) {
    return DOMPurify.sanitize(
      marked.parse(text, { async: false }) as string,
      { USE_PROFILES: { html: true } },
    );
  }

  // Tick the live timer every 100ms while streaming
  $effect(() => {
    if (!loading) return;
    const id = setInterval(() => { now = performance.now(); }, 100);
    return () => clearInterval(id);
  });

  // Auto-scroll on new messages
  $effect(() => {
    messages;
    requestAnimationFrame(() => {
      if (container) container.scrollTop = container.scrollHeight;
    });
  });

  function fmtMs(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function liveElapsed(msg: Message): string {
    if (!msg.startedAt) return '';
    return fmtMs(Math.round(now - msg.startedAt));
  }
</script>

<div bind:this={container} class="messages" aria-live="polite">
  <div class="message-column">
    {#each messages as msg}
      <article class:assistant={msg.role === 'assistant'} class="message">
        <div class="avatar" aria-hidden="true">{msg.role === 'assistant' ? 'A' : 'Y'}</div>
        <div class="message-body">
          <header>
            <strong>{msg.role === 'assistant' ? 'Archon' : 'You'}</strong>
            <time>{msg.timestamp}</time>
          </header>

          <!-- Reasoning & actions (with live timer) -->
          {#if msg.role === 'assistant' && (msg.thinking_steps?.length || msg.tool_calls?.length || msg.skills_used?.length)}
            <details class="reasoning" open={loading && !!msg.startedAt && !msg.content}>
              <summary>
                Reasoning and actions
                <span>
                  {msg.tool_calls?.length || 0} tools · {msg.iterations || '…'} iterations
                  {#if loading && msg.startedAt && !msg.content}
                    · <span style="color:var(--accent);font-variant-numeric:tabular-nums">{liveElapsed(msg)}</span>
                  {/if}
                </span>
              </summary>

              {#if msg.skills_used?.length}
                <p class="detail-label">Skills</p>
                {#each msg.skills_used as skill}
                  <div class="detail-row">
                    <span class="status-dot"></span>
                    <strong>{skill.name}</strong>
                    <span>{skill.description || ''}</span>
                  </div>
                {/each}
              {/if}

              {#if msg.tool_calls?.length}
                <p class="detail-label">Tool calls</p>
                {#each msg.tool_calls as tool}
                  <div class="detail-row">
                    <span class="status-dot"></span>
                    <code>{tool.tool}</code>
                    <span>{JSON.stringify(tool.parameters || {})}</span>
                    {#if tool.elapsed_ms != null}
                      <span style="color:var(--muted);font-size:10px;font-family:var(--font-mono);margin-left:auto;white-space:nowrap">
                        {fmtMs(tool.elapsed_ms)}
                      </span>
                    {/if}
                  </div>
                {/each}
              {/if}

              {#if msg.thinking_steps?.length}
                <p class="detail-label">Steps</p>
                {#each msg.thinking_steps as step}
                  <div class="detail-row" style={step.type === 'compaction' ? 'background:rgba(85,214,190,0.08);border-radius:6px;padding:6px 12px;margin:2px 0' : ''}>
                    <span class="status-dot" style={step.type === 'compaction' ? 'background:var(--accent)' : ''}></span>
                    <span style={step.type === 'compaction' ? 'color:var(--accent);font-weight:600' : ''}>{step.detail}</span>
                    {#if step.elapsed_ms != null}
                      <span style="color:var(--muted);font-size:10px;font-family:var(--font-mono);margin-left:auto;white-space:nowrap">
                        {fmtMs(step.elapsed_ms)}
                      </span>
                    {/if}
                  </div>
                {/each}
              {/if}
            </details>
          {/if}

          <!-- Answer content -->
          {#if msg.role === 'assistant'}
            <div class="answer">{@html markdown(msg.content)}</div>
          {:else}
            <p class="user-copy">{msg.content}</p>
          {/if}

          <!-- Citations / Sources (only after streaming is done) -->
          {#if msg.sources?.length && msg.content && !(loading && msg.startedAt)}
            <details style="margin-top:12px;background:var(--panel);border:1px solid var(--border);border-radius:10px">
              <summary style="padding:10px 12px;cursor:pointer;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted);font-weight:700;list-style:none;display:flex;align-items:center;gap:6px">
                <span style="color:var(--accent);font-size:14px">▸</span> Sources ({msg.sources.length})
              </summary>
              <div style="padding:0 12px 10px">
                {#each msg.sources as src, i}
                  <div style="display:flex;align-items:baseline;gap:8px;padding:4px 0;font-size:12px;{i > 0 ? 'border-top:1px solid var(--border);' : ''}">
                    <span style="color:var(--accent);font-weight:700;font-size:10px;min-width:16px">[{i + 1}]</span>
                    {#if src.url}
                      <a href={src.url} target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                        {src.title || src.url}
                      </a>
                    {:else}
                      <span style="color:var(--secondary)">{src.title}</span>
                    {/if}
                    {#if src.score != null}
                      <span style="color:var(--muted);font-size:10px;margin-left:auto">{(src.score * 100).toFixed(0)}%</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </details>
          {/if}

          <!-- Artifacts -->
          {#if msg.artifacts?.length}
            <div class="artifact-chips">
              {#each msg.artifacts as art}
                <span>Artifact · {art.title}</span>
              {/each}
            </div>
          {/if}
        </div>
      </article>
    {/each}

    <!-- Loading spinner for initial response -->
    {#if loading && messages.at(-1)?.role !== 'assistant'}
      <div class="message assistant">
        <div class="avatar">A</div>
        <div class="thinking" role="status">
          <span></span><span></span><span></span> Starting run…
        </div>
      </div>
    {/if}
  </div>
</div>
