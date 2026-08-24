<script lang="ts">
  let { onSend = (_msg: string, _image?: string) => {}, onCancel = () => {}, disabled = false, streaming = false }: { onSend?: (msg: string, image?: string) => void; onCancel?: () => void; disabled?: boolean; streaming?: boolean } = $props();
  let text = $state(''); let image = $state(''); let preview = $state(''); let textarea: HTMLTextAreaElement; let picker: HTMLInputElement;
  function send() { const value = text.trim(); if ((!value && !image) || disabled) return; onSend(value || 'Describe this image', image || undefined); text = ''; image = ''; preview = ''; }
  function keydown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }
  function resize(e: Event) { const el = e.currentTarget as HTMLTextAreaElement; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 160)}px`; }
  function file(e: Event) { const f = (e.currentTarget as HTMLInputElement).files?.[0]; if (!f?.type.startsWith('image/')) return; if (f.size > 10 * 1024 * 1024) return; const r = new FileReader(); r.onload = () => { preview = String(r.result); image = preview.split(',')[1] || ''; }; r.readAsDataURL(f); }
</script>
<div class="composer-wrap">
  {#if preview}<div class="preview"><img src={preview} alt="Selected upload"><button aria-label="Remove image" onclick={() => { preview = ''; image = ''; }}>×</button></div>{/if}
  <div class="composer">
    <textarea bind:this={textarea} bind:value={text} onkeydown={keydown} oninput={resize} rows="1" placeholder="Ask about a run, test a prompt, or investigate a failure…" aria-label="Message" {disabled}></textarea>
    <input bind:this={picker} type="file" accept="image/*" onchange={file} hidden>
    <button class="icon-button" aria-label="Attach image" onclick={() => picker.click()} disabled={disabled} title="Attach image">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.4 11.6 12 21a6 6 0 0 1-8.5-8.5l10-10a4 4 0 1 1 5.7 5.7l-10 10a2 2 0 0 1-2.9-2.8l9.3-9.3"/></svg>
    </button>
    {#if streaming}<button class="stop-button" onclick={onCancel} aria-label="Stop response"><span></span> Stop</button>
    {:else}<button class="primary send" onclick={send} disabled={disabled || (!text.trim() && !image)}>Send</button>{/if}
  </div>
  <p class="composer-hint">Enter to send · Shift + Enter for a new line</p>
</div>
