<script lang="ts">
  interface Conversation {
    id: string;
    title: string;
    icon: string;
  }

  let { activeId = '', onSelect = (_id: string) => {}, onNew = () => {} }: {
    activeId?: string;
    onSelect?: (id: string) => void;
    onNew?: () => void;
  } = $props();

  let conversations: Conversation[] = $state([
    { id: '1', title: 'Research: AI Agent Patterns', icon: '💬' },
    { id: '2', title: 'Analyze quarterly report', icon: '📄' },
    { id: '3', title: 'Python best practices', icon: '🔍' },
  ]);
</script>

<aside class="w-[280px] bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col shrink-0">
  <!-- Header -->
  <div class="px-5 py-4 border-b border-[var(--border)] flex items-center gap-2.5">
    <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center font-bold text-white text-sm">
      A
    </div>
    <div>
      <div class="text-base font-semibold text-[var(--text-primary)]">Archon</div>
      <div class="text-[11px] text-[var(--text-muted)]">Production AI Agent</div>
    </div>
  </div>

  <!-- New Chat -->
  <button
    onclick={onNew}
    class="mx-4 mt-3 mb-1 px-4 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-[10px] text-[var(--text-primary)] text-sm cursor-pointer flex items-center gap-2 hover:bg-[var(--bg-hover)] hover:border-[var(--accent)] transition-all"
  >
    + New Conversation
  </button>

  <!-- Section label -->
  <div class="px-4 pt-3 pb-1.5 text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
    Today
  </div>

  <!-- Conversations list -->
  <div class="flex-1 overflow-y-auto px-2">
    {#each conversations as conv}
      <button
        onclick={() => onSelect(conv.id)}
        class="w-full text-left px-3 py-2.5 rounded-md cursor-pointer mb-0.5 flex items-center gap-2 transition-colors
          {conv.id === activeId
            ? 'bg-[var(--accent-glow)] border border-[rgba(88,166,255,0.2)]'
            : 'hover:bg-[var(--bg-hover)] border border-transparent'}"
      >
        <span class="text-sm">{conv.icon}</span>
        <span class="text-[13px] truncate flex-1
          {conv.id === activeId ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]'}">
          {conv.title}
        </span>
      </button>
    {/each}
  </div>

  <!-- Footer -->
  <div class="px-4 py-3 border-t border-[var(--border)] flex gap-2">
    <button class="flex-1 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs cursor-pointer text-center hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all">
      📊 Dashboard
    </button>
    <button class="flex-1 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs cursor-pointer text-center hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all">
      ⚙️ Settings
    </button>
  </div>
</aside>
