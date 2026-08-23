<script lang="ts">
  let { onSend = (_msg: string, _image?: string) => {}, disabled = false }: {
    onSend?: (msg: string, image?: string) => void;
    disabled?: boolean;
  } = $props();

  let inputText = $state('');
  let imagePreview = $state('');
  let imageBase64 = $state('');
  let textarea: HTMLTextAreaElement;
  let fileInput: HTMLInputElement;

  function handleSend() {
    const msg = inputText.trim();
    if ((!msg && !imageBase64) || disabled) return;
    onSend(msg || 'Describe this image', imageBase64 || undefined);
    inputText = '';
    imagePreview = '';
    imageBase64 = '';
    if (textarea) textarea.style.height = 'auto';
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function autoResize(e: Event) {
    const el = e.target as HTMLTextAreaElement;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 150) + 'px';
  }

  function handleFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) { alert('Only images'); return; }
    if (file.size > 10 * 1024 * 1024) { alert('Max 10MB'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      imagePreview = result;
      imageBase64 = result.split(',')[1] || '';
    };
    reader.readAsDataURL(file);
  }

  function removeImage() {
    imagePreview = '';
    imageBase64 = '';
    if (fileInput) fileInput.value = '';
  }
</script>

<div class="px-3 sm:px-6 pb-3 sm:pb-6 pt-2 sm:pt-4 w-full max-w-[800px] mx-auto">
  {#if imagePreview}
    <div class="mb-2 relative inline-block">
      <img src={imagePreview} alt="Upload preview" class="max-h-24 rounded-lg border border-[var(--border)]" />
      <button onclick={removeImage} class="absolute -top-2 -right-2 w-6 h-6 bg-[var(--error)] text-white rounded-full text-xs flex items-center justify-center cursor-pointer">✕</button>
    </div>
  {/if}

  <div class="flex items-end bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl sm:rounded-2xl p-1.5 sm:p-2 shadow-lg transition-all focus-within:border-[var(--accent)]">
    <textarea
      bind:this={textarea}
      bind:value={inputText}
      onkeydown={handleKeydown}
      oninput={autoResize}
      placeholder="Ask Archon anything..."
      rows="1"
      {disabled}
      class="flex-1 bg-transparent border-none outline-none text-[var(--text-primary)] text-[14px] sm:text-[15px] resize-none px-2 sm:px-3 py-2 max-h-[150px] leading-relaxed placeholder:text-[var(--text-muted)]"
    ></textarea>

    <input bind:this={fileInput} type="file" accept="image/*" onchange={handleFileSelect} class="hidden" />

    <div class="flex gap-1 p-0.5 sm:p-1">
      <button
        onclick={() => fileInput?.click()}
        class="w-8 h-8 sm:w-9 sm:h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base transition-all
          {imageBase64 ? 'bg-[var(--accent-glow)] text-[var(--accent)]' : 'bg-transparent text-[var(--text-muted)] hover:bg-[var(--bg-hover)]'}"
        title="Upload image"
      >📎</button>
      <button
        onclick={handleSend}
        disabled={(!inputText.trim() && !imageBase64) || disabled}
        class="w-8 h-8 sm:w-9 sm:h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base transition-all
          {(inputText.trim() || imageBase64) && !disabled
            ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]'
            : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] cursor-not-allowed'}"
        title="Send"
      >↑</button>
    </div>
  </div>

  <div class="hidden sm:flex gap-3 px-1 pt-2 text-[11px] text-[var(--text-muted)]">
    <span><span class="px-1.5 bg-[var(--bg-tertiary)] rounded text-[10px] font-mono">Enter</span> Send</span>
    <span><span class="px-1.5 bg-[var(--bg-tertiary)] rounded text-[10px] font-mono">Shift+Enter</span> New line</span>
  </div>
</div>
