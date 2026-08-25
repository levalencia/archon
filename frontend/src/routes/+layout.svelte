<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import AppShell from '$lib/components/AppShell.svelte';

  let { children } = $props();
</script>

{#if $page.url.pathname === '/login'}
  {@render children()}
{:else}
  <AppShell>
    {@render children()}
  </AppShell>
{/if}
