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
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function handleFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      alert('Only image files are supported');
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      alert('Image must be under 10MB');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      imagePreview = result;
      // Extract base64 without the data:image/xxx;base64, prefix
      imageBase64 = result.split(',')[1] || '';
    };
    reader.readAsDataURL(file);
  }

  function removeImage() {
    imagePreview = '';
    imageBase64 = '';
    if (fileInput) fileInput.value = '';
  }

  function triggerFileInput() {
    fileInput?.click();
  }
</script>

<div class="px-6 pb-6 pt-4 max-w-[800px] w-full mx-auto">
  <!-- Image preview -->
  {#if imagePreview}
    <div class="mb-2 relative inline-block">
      <img
        src={imagePreview}
        alt="Upload preview"
        class="max-h-32 rounded-lg border border-[var(--border)]"
      />
      <button
        onclick={removeImage}
        class="absolute -top-2 -right-2 w-6 h-6 bg-[var(--error)] text-white rounded-full text-xs flex items-center justify-center cursor-pointer hover:opacity-80"
      >
        ✕
      </button>
    </div>
  {/if}

  <div class="flex items-end bg-[var(--bg-secondary)] border border-[var(--border)] rounded-2xl p-2 shadow-lg transition-all focus-within:border-[var(--accent)] focus-within:shadow-[0_0_0_2px_var(--accent-glow)]">
    <textarea
      bind:this={textarea}
      bind:value={inputText}
      onkeydown={handleKeydown}
      oninput={autoResize}
      placeholder={imageBase64 ? "Ask about this image..." : "Ask Archon anything... (uploads, research, analysis)"}
      rows="1"
      {disabled}
      class="flex-1 bg-transparent border-none outline-none text-[var(--text-primary)] text-[15px] resize-none px-3 py-2 max-h-[200px] leading-relaxed placeholder:text-[var(--text-muted)]"
    ></textarea>

    <input
      bind:this={fileInput}
      type="file"
      accept="image/*"
      onchange={handleFileSelect}
      class="hidden"
    />

    <div class="flex gap-1 p-1">
      <button
        onclick={triggerFileInput}
        class="w-9 h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base transition-all
          {imageBase64
            ? 'bg-[var(--accent-glow)] text-[var(--accent)]'
            : 'bg-transparent text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'}"
        title="Upload image"
      >
        📎
      </button>
      <button
        onclick={handleSend}
        disabled={(!inputText.trim() && !imageBase64) || disabled}
        class="w-9 h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base transition-all
          {(inputText.trim() || imageBase64) && !disabled
            ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]'
            : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] cursor-not-allowed'}"
        title="Send message"
      >
        ↑
      </button>
    </div>
  </div>

  <div class="flex gap-3 px-1 pt-2 text-[11px] text-[var(--text-muted)]">
    <span class="flex items-center gap-1">
      <span class="px-1.5 bg-[var(--bg-tertiary)] rounded text-[10px] font-mono">Enter</span> Send
    </span>
    <span class="flex items-center gap-1">
      <span class="px-1.5 bg-[var(--bg-tertiary)] rounded text-[10px] font-mono">Shift+Enter</span> New line
    </span>
    <span>📎 Supports image upload (vision)</span>
  </div>
</div>
