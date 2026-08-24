<script lang="ts">
  import { marked } from 'marked'; import DOMPurify from 'dompurify'; import type { Message } from '$lib/types';
  let { messages = [], loading = false }: { messages?: Message[]; loading?: boolean } = $props(); let container: HTMLDivElement;
  function markdown(text: string) { return DOMPurify.sanitize(marked.parse(text, { async: false }) as string, { USE_PROFILES: { html: true } }); }
  $effect(() => { messages; requestAnimationFrame(() => { if (container) container.scrollTop = container.scrollHeight; }); });
</script>
<div bind:this={container} class="messages" aria-live="polite">
  <div class="message-column">
  {#each messages as msg}
    <article class:assistant={msg.role === 'assistant'} class="message">
      <div class="avatar" aria-hidden="true">{msg.role === 'assistant' ? 'A' : 'Y'}</div>
      <div class="message-body"><header><strong>{msg.role === 'assistant' ? 'Archon' : 'You'}</strong><time>{msg.timestamp}</time></header>
        {#if msg.role === 'assistant' && (msg.thinking_steps?.length || msg.tool_calls?.length || msg.skills_used?.length)}
          <details class="reasoning"><summary>Reasoning and actions <span>{msg.tool_calls?.length || 0} tools · {msg.iterations || 1} iterations</span></summary>
            {#if msg.skills_used?.length}<p class="detail-label">Skills</p>{#each msg.skills_used as skill}<div class="detail-row"><span class="status-dot"></span><strong>{skill.name}</strong><span>{skill.description || ''}</span></div>{/each}{/if}
            {#if msg.tool_calls?.length}<p class="detail-label">Tool calls</p>{#each msg.tool_calls as tool}<div class="detail-row"><span class="status-dot"></span><code>{tool.tool}</code><span>{JSON.stringify(tool.parameters || {})}</span></div>{/each}{/if}
            {#if msg.thinking_steps?.length}<p class="detail-label">Steps</p>{#each msg.thinking_steps as step}<div class="detail-row"><span class="status-dot"></span><span>{step.detail}</span></div>{/each}{/if}
          </details>
        {/if}
        {#if msg.role === 'assistant'}<div class="answer">{@html markdown(msg.content)}</div>{:else}<p class="user-copy">{msg.content}</p>{/if}
        {#if msg.artifacts?.length}<div class="artifact-chips">{#each msg.artifacts as art}<span>Artifact · {art.title}</span>{/each}</div>{/if}
      </div>
    </article>
  {/each}
  {#if loading && messages.at(-1)?.role !== 'assistant'}<div class="message assistant"><div class="avatar">A</div><div class="thinking" role="status"><span></span><span></span><span></span> Starting run…</div></div>{/if}
  </div>
</div>
