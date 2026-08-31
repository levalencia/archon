<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { isAuthenticated, getUser, logout } from '$lib/auth';
  import { MessageSquare, LayoutDashboard, FileText, Shield, Settings, Brain, LogOut, Zap, Network } from 'lucide-svelte';

  let { children } = $props();
  let user = $state<{ user_id: string; username: string } | null>(null);

  onMount(() => {
    if (!isAuthenticated()) {
      window.location.href = '/login';
      return;
    }
    user = getUser();
  });

  const navItems = [
    { href: '/', label: 'Chat', icon: MessageSquare },
    { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { href: '/documents', label: 'Documents', icon: FileText },
    { href: '/eval', label: 'Eval', icon: Shield },
    { href: '/memory', label: 'Memory', icon: Brain },
    { href: '/learn/map', label: 'Learn', icon: Network },
    { href: '/settings', label: 'Skills & Integrations', icon: Settings },
  ];

  function isActive(href: string, pathname: string): boolean {
    return href === '/' ? pathname === '/' || pathname.startsWith('/chat/') : pathname.startsWith(href);
  }

  let workbenchRoute = $derived($page.url.pathname === '/' || $page.url.pathname.startsWith('/chat/'));
</script>

{#if workbenchRoute}
  <main class="h-[100dvh] w-full min-w-0 overflow-hidden">{@render children()}</main>
{:else}
  <div class="flex h-[100dvh] w-full overflow-hidden bg-[var(--bg)]">
    <aside class="hidden w-[232px] shrink-0 flex-col border-r border-[var(--border)] bg-[rgba(16,21,29,.97)] md:flex" aria-label="Primary navigation">
      <a href="/" class="flex h-16 min-h-16 items-center gap-3 border-b border-[var(--border)] px-5 no-underline">
        <span class="grid size-8 place-items-center rounded-lg bg-[var(--accent)] font-extrabold text-[#07110f]"><Zap size={16}/></span>
        <span><strong class="block text-sm text-[var(--text)]">Archon</strong><small class="text-[var(--muted)]">Reliability workbench</small></span>
      </a>
      <nav class="flex-1 space-y-1 overflow-y-auto p-3">
        {#each navItems as item}
          <a href={item.href} aria-current={isActive(item.href, $page.url.pathname) ? 'page' : undefined} class="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm no-underline transition-colors {isActive(item.href, $page.url.pathname) ? 'bg-[rgba(85,214,190,.1)] text-[var(--accent)]' : 'text-[var(--secondary)] hover:bg-[var(--raised)] hover:text-[var(--text)]'}">
            <item.icon size={18}/><span>{item.label}</span>
          </a>
        {/each}
      </nav>
      {#if user}<button onclick={logout} class="m-3 flex min-h-11 items-center gap-3 rounded-lg border-0 bg-transparent px-3 text-[var(--danger)] hover:bg-[rgba(255,107,114,.1)]"><LogOut size={18}/> Log out</button>{/if}
    </aside>
    <main class="min-w-0 flex-1 overflow-auto pb-[calc(4.5rem+env(safe-area-inset-bottom))] md:pb-0">{@render children()}</main>
    <nav class="fixed inset-x-0 bottom-0 z-50 grid grid-cols-7 border-t border-[var(--border)] bg-[rgba(16,21,29,.98)] pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden" aria-label="Mobile navigation">
      {#each navItems as item}
        <a href={item.href} aria-label={item.label} aria-current={isActive(item.href, $page.url.pathname) ? 'page' : undefined} class="flex min-h-16 flex-col items-center justify-center gap-1 px-1 text-[9px] no-underline {isActive(item.href, $page.url.pathname) ? 'text-[var(--accent)]' : 'text-[var(--muted)]'}">
          <item.icon size={19}/><span class="max-w-full truncate">{item.label === 'Skills & Integrations' ? 'Settings' : item.label}</span>
        </a>
      {/each}
    </nav>
  </div>
{/if}
