<script lang="ts">
  import type { Conversation } from '$lib/types';
  import { authenticatedFetch } from '$lib/auth';
  let { activeId = '', onSelect = (_id: string) => {}, onNew = () => {}, onClose = () => {} }: { activeId?: string; onSelect?: (id: string) => void; onNew?: () => void; onClose?: () => void } = $props();
  let conversations: Conversation[] = $state([]);
  let loading = $state(true); let error = $state('');
  async function load() { loading = true; error = ''; try { const r = await authenticatedFetch('/api/conversations'); if (!r.ok) throw new Error(`Request failed (${r.status})`); conversations = await r.json(); } catch (e) { error = e instanceof Error ? e.message : 'Unable to load conversations'; } finally { loading = false; } }
  $effect(() => { activeId; load(); });
  async function remove(id: string, e: Event) { e.stopPropagation(); try { const r = await authenticatedFetch(`/api/conversations/${id}`, { method: 'DELETE' }); if (!r.ok && r.status !== 204) throw new Error(); conversations = conversations.filter(c => c.id !== id); if (activeId === id) onNew(); } catch { error = 'Could not delete conversation'; } }
</script>

<div class="sidebar-shell">
  <header class="brand">
    <div class="brand-mark" aria-hidden="true">A</div>
    <div><strong>Archon</strong><span>Reliability Workbench</span></div>
    <button class="icon-button mobile-only" aria-label="Close conversations" onclick={onClose}>×</button>
  </header>
  <button class="primary new-chat" onclick={onNew}>New conversation</button>
  <nav class="conversation-list" aria-label="Conversations">
    <p class="section-label">Recent runs</p>
    {#if loading}<div class="status">Loading conversations…</div>
    {:else if error}<div class="status error" role="alert">{error}<button onclick={load}>Retry</button></div>
    {:else if conversations.length === 0}<div class="status">No conversations yet.</div>
    {:else}{#each conversations as conv}
      <div class:active={conv.id === activeId} class="conversation-row">
        <button class="conversation-select" aria-current={conv.id === activeId ? 'page' : undefined} onclick={() => onSelect(conv.id)}>
          <span class="status-dot"></span><span>{conv.title || 'Untitled'}</span>
        </button>
        <button class="delete" aria-label={`Delete ${conv.title}`} onclick={(e) => remove(conv.id, e)}>×</button>
      </div>
    {/each}{/if}
  </nav>
  <footer class="side-links"><a href="/dashboard">Dashboard</a><a href="/documents">Documents</a><a href="/eval">Evaluations</a><a href="/settings">Settings</a></footer>
</div>
