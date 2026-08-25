<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { isAuthenticated, getUser, logout } from '$lib/auth';
  import {
    MessageSquare, LayoutDashboard, FileText, Shield,
    Settings, Brain, LogOut, Zap, ChevronLeft
  } from 'lucide-svelte';

  let { children } = $props();
  let user = $state<{ user_id: string; username: string } | null>(null);
  let collapsed = $state(false);

  onMount(() => {
    if (!isAuthenticated()) {
      window.location.href = '/login';
      return;
    }
    user = getUser();
  });

  const navItems = [
    { href: '/',          label: 'Chat',      icon: MessageSquare },
    { href: '/dashboard', label: 'Dashboard',  icon: LayoutDashboard },
    { href: '/documents', label: 'Documents',  icon: FileText },
    { href: '/eval',      label: 'Eval',       icon: Shield },
    { href: '/memory',    label: 'Memory',     icon: Brain },
    { href: '/settings',  label: 'Settings',   icon: Settings },
  ];

  function isActive(href: string, pathname: string): boolean {
    if (href === '/') return pathname === '/' || pathname.startsWith('/chat');
    return pathname.startsWith(href);
  }
</script>

<div class="flex h-[100dvh] overflow-hidden bg-[var(--bg)]">
  <!-- Sidebar -->
  <aside
    class="flex flex-col border-r border-[var(--border)] bg-[rgba(16,21,29,0.97)] transition-[width] duration-200 shrink-0"
    class:w-[220px]={!collapsed}
    class:w-[60px]={collapsed}
  >
    <!-- Brand -->
    <div class="h-[60px] flex items-center gap-3 px-4 border-b border-[var(--border)] shrink-0">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] grid place-items-center text-sm font-bold text-white shrink-0">
        A
      </div>
      {#if !collapsed}
        <div class="overflow-hidden">
          <span class="text-sm font-semibold text-[var(--text)]">Archon</span>
        </div>
      {/if}
    </div>

    <!-- Nav links -->
    <nav class="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
      {#each navItems as item}
        {@const active = isActive(item.href, $page.url.pathname)}
        <a
          href={item.href}
          class="flex items-center gap-3 px-3 h-9 rounded-lg text-sm no-underline transition-all
            {active
              ? 'bg-[rgba(85,214,190,0.1)] text-[var(--accent)]'
              : 'text-[var(--secondary)] hover:bg-[var(--raised)] hover:text-[var(--text)]'}"
          title={collapsed ? item.label : undefined}
        >
          <item.icon size={18} class="shrink-0" />
          {#if !collapsed}
            <span>{item.label}</span>
          {/if}
        </a>
      {/each}
    </nav>

    <!-- Footer -->
    <div class="border-t border-[var(--border)] px-2 py-2 space-y-1">
      <button
        onclick={() => collapsed = !collapsed}
        class="flex items-center gap-3 px-3 h-9 w-full rounded-lg text-sm text-[var(--muted)] hover:bg-[var(--raised)] hover:text-[var(--text)] transition-all cursor-pointer border-0 bg-transparent"
      >
        <ChevronLeft size={18} class="shrink-0 transition-transform {collapsed ? 'rotate-180' : ''}" />
        {#if !collapsed}
          <span>Collapse</span>
        {/if}
      </button>
      {#if user}
        <button
          onclick={logout}
          class="flex items-center gap-3 px-3 h-9 w-full rounded-lg text-sm text-[var(--danger)] hover:bg-[rgba(255,107,114,0.1)] transition-all cursor-pointer border-0 bg-transparent"
          title="Log out"
        >
          <LogOut size={18} class="shrink-0" />
          {#if !collapsed}
            <span>Log out</span>
          {/if}
        </button>
      {/if}
    </div>
  </aside>

  <!-- Main content -->
  <main class="flex-1 min-w-0 overflow-auto">
    {@render children()}
  </main>
</div>
