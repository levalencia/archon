<script lang="ts">
  let metrics: any = $state(null);
  let loading = $state(true);

  interface CircuitBreaker {
    state: string;
  }

  async function loadData() {
    loading = true;
    try {
      const [metricsRes, adminRes] = await Promise.all([
        fetch('/api/admin/metrics'),
        fetch('/api/admin/health'),
      ]);
      metrics = { ...(await metricsRes.json()), ...(await adminRes.json()) };

      // Try to load detailed metrics
      const promRes = await fetch('/metrics');
      if (promRes.ok) {
        metrics.prometheus = await promRes.text();
      }
    } catch {
      metrics = { error: 'Cannot connect to backend' };
    }
    loading = false;
  }

  $effect(() => { loadData(); });

  // Auto-refresh every 10s
  $effect(() => {
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  });
</script>

<div class="max-w-6xl mx-auto p-6">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-xl font-semibold text-[var(--text-primary)]">📊 Dashboard</h1>
    <button
      onclick={loadData}
      class="px-3 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer"
    >
      ↻ Refresh
    </button>
  </div>

  {#if loading && !metrics}
    <div class="text-[var(--text-muted)] text-center py-12">Loading metrics...</div>
  {:else if metrics}
    <!-- Status cards -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4">
        <div class="text-[11px] text-[var(--text-muted)] mb-1">Status</div>
        <div class="text-2xl font-bold {metrics.status === 'healthy' ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
          {metrics.status === 'healthy' ? '● Healthy' : '● Down'}
        </div>
      </div>
      <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4">
        <div class="text-[11px] text-[var(--text-muted)] mb-1">Uptime</div>
        <div class="text-2xl font-bold text-[var(--text-primary)]">
          {Math.round((metrics.uptime_seconds || 0) / 60)}m
        </div>
      </div>
      <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4">
        <div class="text-[11px] text-[var(--text-muted)] mb-1">Circuit Breakers</div>
        <div class="text-2xl font-bold text-[var(--success)]">
          {metrics.circuit_breaker_count || 0} active
        </div>
      </div>
      <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4">
        <div class="text-[11px] text-[var(--text-muted)] mb-1">Services</div>
        <div class="text-2xl font-bold text-[var(--text-primary)]">
          {Object.keys(metrics.services || {}).length}
        </div>
      </div>
    </div>

    <!-- Circuit Breakers -->
    <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
      <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">⚡ Circuit Breakers</h2>
      {#if Object.keys(metrics.circuit_breakers || {}).length === 0}
        <div class="text-sm text-[var(--text-muted)]">No circuit breakers registered yet</div>
      {:else}
        <div class="space-y-2">
          {#each Object.entries(metrics.circuit_breakers || {}) as [name, cb]}
            {@const circuitBreaker = cb as CircuitBreaker}
            <div class="flex items-center justify-between px-4 py-2 bg-[var(--bg-tertiary)] rounded-lg">
              <span class="text-sm text-[var(--text-primary)]">{name}</span>
              <span class="text-xs font-mono px-2 py-0.5 rounded
                {circuitBreaker.state === 'closed' ? 'bg-[rgba(63,185,80,0.15)] text-[var(--success)]' :
                 circuitBreaker.state === 'open' ? 'bg-[rgba(248,81,73,0.15)] text-[var(--error)]' :
                 'bg-[rgba(210,153,34,0.15)] text-[var(--warning)]'}">
                {circuitBreaker.state}
              </span>
            </div>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Audit Log -->
    <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
      <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">📋 Recent Audit</h2>
      {#await fetch('/api/admin/audit?limit=10').then(r => r.json())}
        <div class="text-sm text-[var(--text-muted)]">Loading...</div>
      {:then data}
        {#if data.count === 0}
          <div class="text-sm text-[var(--text-muted)]">No audit entries yet</div>
        {:else}
          <div class="space-y-1">
            {#each data.entries as entry}
              <div class="flex items-center gap-3 px-3 py-1.5 text-xs font-mono text-[var(--text-secondary)]">
                <span class="text-[var(--text-muted)]">{entry.timestamp}</span>
                <span class="text-[var(--accent)]">{entry.action}</span>
                <span>{entry.resource}</span>
                <span class="{entry.security_level === 'warning' ? 'text-[var(--warning)]' : 'text-[var(--text-muted)]'}">
                  {entry.security_level}
                </span>
              </div>
            {/each}
          </div>
        {/if}
      {/await}
    </section>

    <!-- Prometheus raw -->
    {#if metrics.prometheus}
      <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
        <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">📈 Prometheus Metrics</h2>
        <pre class="text-xs font-mono text-[var(--text-muted)] overflow-x-auto max-h-64 overflow-y-auto">{metrics.prometheus}</pre>
      </section>
    {/if}
  {/if}
</div>
