<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  import { Brain, Database, Thermometer, Archive, RotateCcw, HardDrive } from 'lucide-svelte';

  let tiers: any = $state(null);
  let context: any = $state(null);
  let checkpoints: any[] = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Context window derived values
  const ctxUsed = $derived(context?.used_tokens ?? 1840);
  const ctxTotal = $derived(context?.max_tokens ?? 4096);
  const ctxPct = $derived(Math.round((ctxUsed / ctxTotal) * 100));
  const ctxSegments = $derived(context?.segments ?? [
    { label: 'System prompt', tokens: 320 },
    { label: 'History', tokens: 1200 },
    { label: 'Tools', tokens: 320 },
  ]);

  async function loadMemory() {
    loading = true;
    error = '';
    try {
      const [tiersRes, contextRes, checkpointsRes] = await Promise.allSettled([
        authenticatedFetch('/api/memory/tiers'),
        authenticatedFetch('/api/memory/context'),
        authenticatedFetch('/api/memory/checkpoints'),
      ]);

      if (tiersRes.status === 'fulfilled' && tiersRes.value.ok)
        tiers = await tiersRes.value.json();
      if (contextRes.status === 'fulfilled' && contextRes.value.ok)
        context = await contextRes.value.json();
      if (checkpointsRes.status === 'fulfilled' && checkpointsRes.value.ok)
        checkpoints = await checkpointsRes.value.json();
    } catch {
      error = 'Failed to load memory data';
    }
    loading = false;
  }

  async function restoreCheckpoint(id: string) {
    await authenticatedFetch(`/api/memory/checkpoints/${id}/restore`, { method: 'POST' });
    await loadMemory();
  }

  $effect(() => { loadMemory(); });

  const tierConfig = [
    {
      key: 'hot',
      label: 'Hot',
      sublabel: 'Redis',
      description: 'Current conversation context',
      detail: 'Last N messages, 24h TTL',
      color: 'var(--error)',
      icon: Thermometer,
      status: 'Active',
    },
    {
      key: 'warm',
      label: 'Warm',
      sublabel: 'PostgreSQL',
      description: 'Summarized history, searchable',
      detail: 'Encrypted, indexed',
      color: 'var(--warning)',
      icon: Database,
      status: 'Persistent',
    },
    {
      key: 'cold',
      label: 'Cold',
      sublabel: 'Archive',
      description: 'Full encrypted archives',
      detail: 'Compressed, blob storage',
      color: 'var(--accent)',
      icon: Archive,
      status: 'Archived',
    },
  ];
</script>

<div class="max-w-4xl mx-auto p-6 space-y-6">
  <!-- Page header -->
  <div class="flex items-center gap-3">
    <div class="p-2 rounded-lg bg-[var(--bg-tertiary)]">
      <Brain size={20} class="text-[var(--purple)]" />
    </div>
    <div>
      <h1 class="text-xl font-semibold text-[var(--text-primary)]">Memory Inspector</h1>
      <p class="text-xs text-[var(--text-muted)]">Tiered memory system & context visualization</p>
    </div>
  </div>

  <!-- Memory Tiers -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center gap-2 mb-5">
      <Database size={16} class="text-[var(--accent)]" />
      <h2 class="text-base font-semibold text-[var(--text-primary)]">Memory Tiers</h2>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      {#each tierConfig as tier}
        {@const tierData = tiers?.[tier.key]}
        <div class="p-4 bg-[var(--bg-tertiary)] rounded-lg border-l-4 transition-colors hover:bg-[var(--bg-hover)]"
          style="border-left-color: {tier.color}">
          <div class="flex items-center gap-2 mb-2">
            <tier.icon size={14} style="color: {tier.color}" />
            <span class="text-sm font-semibold text-[var(--text-primary)]">{tier.label}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-muted)]">
              {tier.sublabel}
            </span>
          </div>
          <p class="text-xs text-[var(--text-muted)] mb-1">{tier.description}</p>
          <p class="text-[11px] text-[var(--text-muted)] mb-3">{tier.detail}</p>

          <!-- Usage bar -->
          {#if tierData?.usage != null}
            <div class="mb-2">
              <div class="flex justify-between text-[10px] text-[var(--text-muted)] mb-1">
                <span>Usage</span>
                <span>{Math.round(tierData.usage * 100)}%</span>
              </div>
              <div class="h-1.5 bg-[var(--bg-primary)] rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  style="width: {tierData.usage * 100}%; background: {tier.color}"
                ></div>
              </div>
            </div>
            <div class="text-xs font-medium" style="color: {tier.color}">
              {tierData.entries ?? 0} entries
            </div>
          {:else}
            <div class="text-sm font-bold" style="color: {tier.color}">
              {tier.status}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  <!-- Context Window -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center gap-2 mb-5">
      <Brain size={16} class="text-[var(--purple)]" />
      <h2 class="text-base font-semibold text-[var(--text-primary)]">Context Window</h2>
    </div>

    <div class="flex items-center gap-4 mb-3">
      <div class="flex-1 h-3 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
        <div
          class="h-full rounded-full transition-all duration-700
            {ctxPct > 80 ? 'bg-[var(--error)]' : ctxPct > 60 ? 'bg-[var(--warning)]' : 'bg-gradient-to-r from-[var(--accent)] to-[var(--purple)]'}"
          style="width: {ctxPct}%"
        ></div>
      </div>
      <span class="text-xs text-[var(--text-muted)] whitespace-nowrap">
        {ctxPct}% used ({ctxUsed.toLocaleString()} / {ctxTotal.toLocaleString()} tokens)
      </span>
    </div>

    <!-- Segment breakdown -->
    <div class="flex flex-wrap gap-3 text-xs text-[var(--text-muted)]">
      {#each ctxSegments as seg}
        <div class="flex items-center gap-1.5 px-2.5 py-1 bg-[var(--bg-tertiary)] rounded-md">
          <div class="w-2 h-2 rounded-full bg-[var(--accent)]"></div>
          {seg.label}: {seg.tokens?.toLocaleString()} tokens
        </div>
      {/each}
      <div class="flex items-center gap-1.5 px-2.5 py-1 bg-[var(--bg-tertiary)] rounded-md">
        <div class="w-2 h-2 rounded-full bg-[var(--text-muted)]"></div>
        Reserved: {(ctxTotal - ctxUsed).toLocaleString()} tokens
      </div>
    </div>
  </section>

  <!-- Checkpoints -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center gap-2 mb-4">
      <HardDrive size={16} class="text-[var(--accent)]" />
      <h2 class="text-base font-semibold text-[var(--text-primary)]">Checkpoints</h2>
    </div>

    {#if checkpoints.length === 0}
      <div class="text-center py-6 text-[var(--text-muted)]">
        <Archive size={28} class="mx-auto mb-2 opacity-40" />
        <p class="text-sm">No checkpoints yet</p>
        <p class="text-xs mt-1">Checkpoints are created automatically every 10 messages</p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each checkpoints as cp}
          <div class="flex items-center justify-between px-4 py-3 bg-[var(--bg-tertiary)] rounded-lg
            border border-transparent hover:border-[var(--border)] transition-colors group">
            <div>
              <span class="text-sm text-[var(--text-primary)]">{cp.label || `Checkpoint ${cp.id}`}</span>
              <span class="text-xs text-[var(--text-muted)] ml-2">
                {cp.message_count ?? '?'} messages
              </span>
              {#if cp.created_at}
                <span class="text-[10px] text-[var(--text-muted)] ml-2">
                  {new Date(cp.created_at).toLocaleString()}
                </span>
              {/if}
            </div>
            <button
              onclick={() => restoreCheckpoint(cp.id)}
              class="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs
                text-[var(--text-muted)] hover:text-[var(--accent)] hover:bg-[var(--accent-glow)]
                transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
              title="Restore checkpoint"
            >
              <RotateCcw size={12} />
              Restore
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</div>
