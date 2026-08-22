<script lang="ts">
  let { onSend = (_msg: string) => {}, disabled = false }: {
    onSend?: (msg: string) => void;
    disabled?: boolean;
  } = $props();

  let inputText = $state('');
  let textarea: HTMLTextAreaElement;

  function handleSend() {
    const msg = inputText.trim();
    if (!msg || disabled) return;
    onSend(msg);
    inputText = '';
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
</script>

<div class="px-6 pb-6 pt-4 max-w-[800px] w-full mx-auto">
  <div class="flex items-end bg-[var(--bg-secondary)] border border-[var(--border)] rounded-2xl p-2 shadow-lg transition-all focus-within:border-[var(--accent)] focus-within:shadow-[0_0_0_2px_var(--accent-glow)]">
    <textarea
      bind:this={textarea}
      bind:value={inputText}
      onkeydown={handleKeydown}
      oninput={autoResize}
      placeholder="Ask Archon anything... (uploads, research, analysis)"
      rows="1"
      {disabled}
      class="flex-1 bg-transparent border-none outline-none text-[var(--text-primary)] text-[15px] resize-none px-3 py-2 max-h-[200px] leading-relaxed placeholder:text-[var(--text-muted)]"
    ></textarea>

    <div class="flex gap-1 p-1">
      <button
        class="w-9 h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base bg-transparent text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all"
        title="Upload document"
      >
        📎
      </button>
      <button
        onclick={handleSend}
        disabled={!inputText.trim() || disabled}
        class="w-9 h-9 rounded-lg border-none cursor-pointer flex items-center justify-center text-base transition-all
          {inputText.trim() && !disabled
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
    <span>Model: Claude Opus 4.6 via Azure Foundry</span>
  </div>
</div>
