<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  import { Brain, Database, Thermometer, Archive, RotateCcw, KeyRound, ShieldCheck } from 'lucide-svelte';
  import { getMemoryRotation, rotateMemoryKeys, type MemoryRotationStatus } from '$lib/memory';

  let tiers: any = $state(null);
  let context: any = $state(null);
  let rotation: MemoryRotationStatus | null = $state(null);
  let rotationBusy = $state(false);
  let rotationError = $state('');
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
    rotationError = '';
    try {
      const [tiersRes, contextRes, rotationRes] = await Promise.allSettled([
        authenticatedFetch('/api/memory/tiers'),
        authenticatedFetch('/api/memory/context'),
        getMemoryRotation(),
      ]);

      if (tiersRes.status === 'fulfilled' && tiersRes.value.ok)
        tiers = await tiersRes.value.json();
      if (contextRes.status === 'fulfilled' && contextRes.value.ok)
        context = await contextRes.value.json();
      if (rotationRes.status === 'fulfilled') rotation = rotationRes.value;
      else rotationError = 'Rotation status unavailable';
    } catch {
      error = 'Failed to load memory data';
    }
    loading = false;
  }

  async function rotateBatch() {
    if (rotationBusy) return;
    rotationBusy = true;
    rotationError = '';
    try {
      rotation = await rotateMemoryKeys('default', 100);
    } catch (cause) {
      rotationError = cause instanceof Error ? cause.message : 'Rotation failed';
    } finally {
      rotationBusy = false;
    }
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

  <!-- Online key rotation -->
  <section class="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5" aria-labelledby="rotation-heading">
    <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-2">
        <KeyRound size={16} class="text-[var(--accent)]" />
        <div>
          <h2 id="rotation-heading" class="text-base font-semibold text-[var(--text-primary)]">Encryption key rotation</h2>
          <p class="mt-0.5 text-xs text-[var(--text-muted)]">Default project · metadata only</p>
        </div>
      </div>
      {#if rotation}
        <span class="w-fit rounded-full px-2.5 py-1 text-xs font-medium {rotation.complete ? 'bg-[rgba(85,214,190,.12)] text-[var(--accent)]' : 'bg-[rgba(240,189,98,.12)] text-[var(--warning)]'}">
          {rotation.complete ? 'Current' : `${rotation.remaining} remaining`}
        </span>
      {/if}
    </div>

    {#if rotationError}
      <div class="rounded-lg border border-[rgba(245,101,101,.35)] bg-[rgba(245,101,101,.08)] p-3 text-sm text-[var(--error)]" role="alert">{rotationError}</div>
    {:else if loading && !rotation}
      <div class="text-sm text-[var(--text-muted)]" aria-live="polite">Loading rotation status…</div>
    {:else if rotation}
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div class="rounded-lg bg-[var(--bg-tertiary)] p-3"><span class="text-[11px] text-[var(--text-muted)]">Active version</span><strong class="mt-1 block font-mono text-lg text-[var(--text-primary)]">v{rotation.active_version}</strong></div>
        <div class="rounded-lg bg-[var(--bg-tertiary)] p-3"><span class="text-[11px] text-[var(--text-muted)]">Rows remaining</span><strong class="mt-1 block font-mono text-lg text-[var(--text-primary)]">{rotation.remaining}</strong></div>
        <div class="rounded-lg bg-[var(--bg-tertiary)] p-3"><span class="text-[11px] text-[var(--text-muted)]">Version counts</span><strong class="mt-1 block font-mono text-sm text-[var(--text-primary)]">{Object.entries(rotation.version_counts).map(([version, count]) => `v${version}: ${count}`).join(' · ') || 'No rows'}</strong></div>
      </div>
      {#if rotation.retirement_requires_legacy_writer_drain}
        <div class="mt-3 flex items-start gap-2 rounded-lg border border-[rgba(240,189,98,.3)] bg-[rgba(240,189,98,.07)] p-3 text-xs text-[var(--warning)]">
          <ShieldCheck size={16} class="mt-0.5 shrink-0" />
          <span>Retirement requires the documented legacy-writer drain, even when remaining reaches zero.</span>
        </div>
      {/if}
      <div class="mt-4 flex justify-end">
        <button
          type="button"
          onclick={rotateBatch}
          disabled={rotationBusy || rotation.complete}
          class="inline-flex min-h-11 items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-[var(--bg-primary)] transition-opacity disabled:cursor-not-allowed disabled:opacity-45"
        >
          <RotateCcw size={15} class={rotationBusy ? 'animate-spin' : ''} />
          {rotationBusy ? 'Rotating…' : rotation.complete ? 'No rotation needed' : 'Rotate next 100 rows'}
        </button>
      </div>
    {/if}
  </section>

</div>
