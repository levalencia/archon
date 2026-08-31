<script lang="ts">
  import type { Conversation } from '$lib/types';
  import { authenticatedFetch } from '$lib/auth';
  import { LayoutDashboard, FileText, ShieldCheck, Brain, Settings, MessageSquarePlus, X, Network } from 'lucide-svelte';
  let { activeId = '', onSelect = (_id: string) => {}, onNew = () => {}, onClose = () => {} }: { activeId?: string; onSelect?: (id: string) => void; onNew?: () => void; onClose?: () => void } = $props();
  let conversations: Conversation[] = $state([]);
  let loading = $state(true); let error = $state('');
  const destinations = [
    { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { href: '/documents', label: 'Documents', icon: FileText },
    { href: '/eval', label: 'Eval', icon: ShieldCheck },
    { href: '/memory', label: 'Memory', icon: Brain },
    { href: '/learn', label: 'Visual learning', icon: Network },
    { href: '/settings', label: 'Skills & Integrations', icon: Settings },
  ];
  async function load() { loading = true; error = ''; try { const r = await authenticatedFetch('/api/conversations'); if (!r.ok) throw new Error(`Request failed (${r.status})`); conversations = await r.json(); } catch (e) { error = e instanceof Error ? e.message : 'Unable to load conversations'; } finally { loading = false; } }
  $effect(() => { activeId; load(); });
  async function remove(id: string, e: Event) { e.stopPropagation(); try { const r = await authenticatedFetch(`/api/conversations/${id}`, { method: 'DELETE' }); if (!r.ok && r.status !== 204) throw new Error(); conversations = conversations.filter(c => c.id !== id); if (activeId === id) onNew(); } catch { error = 'Could not delete conversation'; } }
</script>

<div class="sidebar-shell">
  <header class="brand !h-16 !px-4 !py-0">
    <a href="/" class="flex min-h-11 items-center gap-3 no-underline">
      <span class="grid size-8 place-items-center rounded-lg bg-[var(--accent)] font-extrabold text-[#07110f]">A</span>
      <span><strong>Archon</strong><small>Reliability workbench</small></span>
    </a>
    <button class="icon-button mobile-only ml-auto" aria-label="Close conversations" onclick={onClose}><X size={20}/></button>
  </header>
  <button class="primary new-chat flex items-center gap-2" onclick={onNew}><MessageSquarePlus size={16}/> New conversation</button>
  <nav class="conversation-list" aria-label="Conversations">
    <p class="section-label">Recent runs</p>
    {#if loading}<div class="status">Loading conversations…</div>
    {:else if error}<div class="status error" role="alert">{error}<button onclick={load}>Retry</button></div>
    {:else if conversations.length === 0}<div class="status">No conversations yet.</div>
    {:else}{#each conversations as conv}
      <div class:active={conv.id === activeId} class="conversation-row">
        <button class="conversation-select" aria-current={conv.id === activeId ? 'page' : undefined} onclick={() => onSelect(conv.id)}><span class="status-dot"></span><span>{conv.title || 'Untitled'}</span></button>
        <button class="delete" aria-label={`Delete ${conv.title}`} onclick={(e) => remove(conv.id, e)}>×</button>
      </div>
    {/each}{/if}
  </nav>
  <nav class="border-t border-[var(--border)] p-2" aria-label="Workspace destinations">
    {#each destinations as item}
      <a href={item.href} class="flex min-h-11 items-center gap-3 rounded-lg px-3 text-xs text-[var(--secondary)] no-underline hover:bg-[var(--raised)] hover:text-[var(--text)]"><item.icon size={16}/><span>{item.label}</span></a>
    {/each}
  </nav>
</div>
