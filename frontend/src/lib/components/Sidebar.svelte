<script lang="ts">
  interface Conversation {
    id: string;
    title: string;
    created_at: string;
  }

  let { activeId = '', onSelect = (_id: string) => {}, onNew = () => {} }: {
    activeId?: string;
    onSelect?: (id: string) => void;
    onNew?: () => void;
  } = $props();

  let conversations: Conversation[] = $state([]);
  let loading = $state(true);

  async function loadConversations() {
    loading = true;
    try {
      const r = await fetch('/api/conversations');
      if (r.ok) {
        conversations = await r.json();
      }
    } catch {
      // Backend might not be running
    }
    loading = false;
  }

  // Load on mount
  $effect(() => { loadConversations(); });

  // Reload when activeId changes (new conversation created)
  $effect(() => {
    if (activeId) loadConversations();
  });

  // Group by date
  function groupByDate(convs: Conversation[]): { label: string; items: Conversation[] }[] {
    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    const groups: { label: string; items: Conversation[] }[] = [];
    const todayItems: Conversation[] = [];
    const yesterdayItems: Conversation[] = [];
    const olderItems: Conversation[] = [];

    for (const c of convs) {
      const date = new Date(c.created_at).toDateString();
      if (date === today) todayItems.push(c);
      else if (date === yesterday) yesterdayItems.push(c);
      else olderItems.push(c);
    }

    if (todayItems.length) groups.push({ label: 'Today', items: todayItems });
    if (yesterdayItems.length) groups.push({ label: 'Yesterday', items: yesterdayItems });
    if (olderItems.length) groups.push({ label: 'Previous', items: olderItems });

    return groups;
  }

  async function deleteConversation(id: string, e: Event) {
    e.stopPropagation();
    await fetch(`/api/conversations/${id}`, { method: 'DELETE' });
    conversations = conversations.filter(c => c.id !== id);
    if (activeId === id) onNew();
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="px-4 py-3 border-b border-[var(--border)] flex items-center gap-2.5 shrink-0">
    <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center font-bold text-white text-sm">A</div>
    <div>
      <div class="text-[15px] font-semibold text-[var(--text-primary)]">Archon</div>
      <div class="text-[11px] text-[var(--text-muted)]">Production AI Agent</div>
    </div>
  </div>

  <!-- New Chat -->
  <button onclick={onNew}
    class="mx-3 mt-3 mb-1 px-4 py-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm cursor-pointer flex items-center gap-2 hover:bg-[var(--bg-hover)] hover:border-[var(--accent)] transition-all shrink-0">
    + New Conversation
  </button>

  <!-- Conversations list -->
  <div class="flex-1 overflow-y-auto px-2 mt-2">
    {#if loading}
      <div class="text-center text-xs text-[var(--text-muted)] py-4">Loading...</div>
    {:else if conversations.length === 0}
      <div class="text-center text-xs text-[var(--text-muted)] py-4">No conversations yet</div>
    {:else}
      {#each groupByDate(conversations) as group}
        <div class="px-2 pt-3 pb-1 text-[11px] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
          {group.label}
        </div>
        {#each group.items as conv}
          <button
            onclick={() => onSelect(conv.id)}
            class="w-full text-left px-3 py-2 rounded-md cursor-pointer mb-0.5 flex items-center gap-2 transition-colors group
              {conv.id === activeId
                ? 'bg-[var(--accent-glow)] border border-[rgba(88,166,255,0.2)]'
                : 'hover:bg-[var(--bg-hover)] border border-transparent'}"
          >
            <span class="text-sm">💬</span>
            <span class="text-[13px] truncate flex-1
              {conv.id === activeId ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]'}">
              {conv.title || 'Untitled'}
            </span>
            <span
              role="button"
              tabindex="0"
              onclick={(e) => deleteConversation(conv.id, e)}
              onkeydown={(e) => { if (e.key === "Enter") deleteConversation(conv.id, e); }}
              class="opacity-0 group-hover:opacity-100 text-[var(--text-muted)] hover:text-[var(--error)] text-xs transition-opacity cursor-pointer"
            >✕</span>
          </button>
        {/each}
      {/each}
    {/if}
  </div>

  <!-- Footer nav -->
  <div class="px-3 py-3 border-t border-[var(--border)] flex gap-2 shrink-0">
    <a href="/dashboard" class="flex-1 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs text-center hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all no-underline">📊 Dashboard</a>
    <a href="/settings" class="flex-1 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs text-center hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all no-underline">⚙️ Settings</a>
  </div>
</div>
