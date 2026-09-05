<script lang="ts">
  import type { ExecutionMode } from '$lib/types';

  let {
    onSend = (_msg: string, _image?: string) => {},
    onCancel = () => {},
    disabled = false,
    streaming = false,
    executionMode = $bindable<ExecutionMode>('auto'),
  }: {
    onSend?: (msg: string, image?: string) => void;
    onCancel?: () => void;
    disabled?: boolean;
    streaming?: boolean;
    executionMode?: ExecutionMode;
  } = $props();
  let text = $state(''); let image = $state(''); let preview = $state(''); let textarea: HTMLTextAreaElement; let picker: HTMLInputElement;
  function send() { const value = text.trim(); if ((!value && !image) || disabled) return; onSend(value || 'Describe this image', image || undefined); text = ''; image = ''; preview = ''; }
  function keydown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }
  function resize(e: Event) { const el = e.currentTarget as HTMLTextAreaElement; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 160)}px`; }
  const allowedImages = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
  function file(e: Event) { const f = (e.currentTarget as HTMLInputElement).files?.[0]; if (!f || !allowedImages.has(f.type) || f.size > 5 * 1024 * 1024) return; const r = new FileReader(); r.onload = () => { preview = String(r.result); image = preview; }; r.readAsDataURL(f); }
</script>
<div class="composer-wrap">
  <fieldset class="execution-mode" disabled={streaming}>
    <legend>Execution mode</legend>
    {#each ['auto', 'single', 'team'] as mode}
      <label class:active={executionMode === mode}>
        <input
          type="radio"
          name="execution-mode"
          value={mode}
          bind:group={executionMode}
          disabled={streaming}
          title={mode === 'auto' ? 'Archon chooses Single or Team' : mode === 'single' ? 'Use one governed agent' : 'Use bounded specialist agents'}
        />
        {mode[0].toUpperCase() + mode.slice(1)}
      </label>
    {/each}
  </fieldset>
  {#if preview}<div class="preview"><img src={preview} alt="Selected upload"><button aria-label="Remove image" onclick={() => { preview = ''; image = ''; }}>×</button></div>{/if}
  <div class="composer">
    <textarea bind:this={textarea} bind:value={text} onkeydown={keydown} oninput={resize} rows="1" placeholder="Ask about a run, test a prompt, or investigate a failure…" aria-label="Message" {disabled}></textarea>
    <input bind:this={picker} type="file" accept="image/png,image/jpeg,image/webp,image/gif" onchange={file} hidden>
    <button class="icon-button" aria-label="Attach image" onclick={() => picker.click()} disabled={disabled} title="Attach image">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l10-10a4 4 0 1 1 5.7 5.7l-10 10a2 2 0 0 1-2.9-2.8l9.3-9.3"/></svg>
    </button>
    {#if streaming}<button class="stop-button" onclick={onCancel} aria-label="Stop response"><span></span> Stop</button>
    {:else}<button class="primary send" onclick={send} disabled={disabled || (!text.trim() && !image)}>Send</button>{/if}
  </div>
  <p class="composer-hint">Enter to send · Shift + Enter for a new line</p>
</div>

<style>
  .execution-mode { display: flex; align-items: center; gap: .35rem; margin: 0 0 .5rem; padding: 0; border: 0; }
  .execution-mode legend { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .execution-mode label { min-height: 40px; display: inline-flex; align-items: center; border: 1px solid var(--border); border-radius: 999px; background: var(--panel-2); color: var(--muted); padding: .4rem .8rem; font-size: .72rem; font-weight: 700; text-transform: capitalize; cursor: pointer; }
  .execution-mode label.active { border-color: var(--accent); background: var(--accent-glow); color: var(--accent); }
  .execution-mode input { position: absolute; width: 1px; height: 1px; opacity: 0; }
  .execution-mode label:has(input:focus-visible) { outline: 2px solid var(--accent); outline-offset: 2px; }
  .execution-mode label:has(input:disabled) { cursor: not-allowed; opacity: .55; }
</style>
