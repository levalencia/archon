<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  import { Activity, Shield, Clock, AlertTriangle, Server, RefreshCw, BarChart3, FileText } from 'lucide-svelte';

  let metrics: any = $state(null);
  let loading = $state(true);

  interface CircuitBreaker {
    state: string;
  }

  async function loadData() {
    loading = true;
    try {
      const [metricsRes, adminRes] = await Promise.all([
        authenticatedFetch('/api/admin/metrics'),
        authenticatedFetch('/api/admin/health'),
      ]);
      metrics = { ...(await metricsRes.json()), ...(await adminRes.json()) };

      const promRes = await authenticatedFetch('/metrics');
      if (promRes.ok) {
        metrics.prometheus = await promRes.text();
      }
    } catch {
      metrics = { error: 'Cannot connect to backend' };
    }
    loading = false;
  }

  $effect(() => { loadData(); });

  $effect(() => {
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  });
</script>

<div class="page-container">
  <header class="page-header">
    <div class="page-title">
      <Activity size={22} strokeWidth={2} class="icon-accent" />
      <h1>Dashboard</h1>
    </div>
    <button onclick={loadData} class="btn-secondary">
      <RefreshCw size={14} strokeWidth={2} />
      Refresh
    </button>
  </header>

  {#if loading && !metrics}
    <div class="empty-state">
      <RefreshCw size={24} class="icon-muted animate-spin" />
      <span>Loading metrics...</span>
    </div>
  {:else if metrics?.error}
    <div class="empty-state error">
      <AlertTriangle size={24} class="icon-error" />
      <span>{metrics.error}</span>
    </div>
  {:else if metrics}
    <!-- Status Cards -->
    <div class="card-grid">
      <div class="stat-card">
        <div class="stat-label">
          <Activity size={14} />
          Status
        </div>
        <div class="stat-value" class:success={metrics.status === 'healthy'} class:error={metrics.status !== 'healthy'}>
          {metrics.status === 'healthy' ? 'Healthy' : 'Down'}
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">
          <Clock size={14} />
          Uptime
        </div>
        <div class="stat-value">
          {Math.round((metrics.uptime_seconds || 0) / 60)}m
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">
          <Shield size={14} />
          Circuit Breakers
        </div>
        <div class="stat-value success">
          {metrics.circuit_breaker_count || 0} active
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">
          <Server size={14} />
          Services
        </div>
        <div class="stat-value">
          {Object.keys(metrics.services || {}).length}
        </div>
      </div>
    </div>

    <!-- Circuit Breakers -->
    <section class="card">
      <h2 class="card-title">
        <Shield size={16} strokeWidth={2} class="icon-accent" />
        Circuit Breakers
      </h2>
      {#if Object.keys(metrics.circuit_breakers || {}).length === 0}
        <div class="empty-hint">No circuit breakers registered yet</div>
      {:else}
        <div class="list-stack">
          {#each Object.entries(metrics.circuit_breakers || {}) as [name, cb]}
            {@const circuitBreaker = cb as CircuitBreaker}
            <div class="list-row">
              <span class="list-row-label">{name}</span>
              <span class="badge"
                class:badge-success={circuitBreaker.state === 'closed'}
                class:badge-error={circuitBreaker.state === 'open'}
                class:badge-warning={circuitBreaker.state === 'half-open'}
              >
                {circuitBreaker.state}
              </span>
            </div>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Audit Log -->
    <section class="card">
      <h2 class="card-title">
        <FileText size={16} strokeWidth={2} class="icon-accent" />
        Recent Audit
      </h2>
      {#await authenticatedFetch('/api/admin/audit-log?limit=10').then(r => r.json())}
        <div class="empty-hint">Loading...</div>
      {:then data}
        {#if data.count === 0}
          <div class="empty-hint">No audit entries yet</div>
        {:else}
          <div class="audit-list">
            {#each data.entries as entry}
              <div class="audit-row">
                <span class="audit-time">
                  <Clock size={11} />
                  {entry.timestamp}
                </span>
                <span class="audit-action">{entry.action}</span>
                <span class="audit-resource">{entry.resource}</span>
                <span class="badge"
                  class:badge-warning={entry.security_level === 'warning'}
                  class:badge-muted={entry.security_level !== 'warning'}
                >
                  {entry.security_level}
                </span>
              </div>
            {/each}
          </div>
        {/if}
      {/await}
    </section>

    <!-- Prometheus Metrics -->
    {#if metrics.prometheus}
      <section class="card">
        <h2 class="card-title">
          <BarChart3 size={16} strokeWidth={2} class="icon-accent" />
          Prometheus Metrics
        </h2>
        <pre class="metrics-pre">{metrics.prometheus}</pre>
      </section>
    {/if}
  {/if}
</div>

<style>
  .page-container {
    max-width: 72rem;
    margin: 0 auto;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .page-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .page-title h1 {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .btn-secondary {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 0.75rem;
    background: var(--bg-tertiary);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .btn-secondary:hover {
    color: var(--text-primary);
    border-color: var(--accent);
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 3rem 0;
    color: var(--text-muted);
    font-size: 0.875rem;
  }

  .empty-state.error {
    color: var(--error);
  }

  .card-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
  }

  .stat-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1rem;
  }

  .stat-label {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.6875rem;
    color: var(--text-muted);
    margin-bottom: 0.375rem;
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text-primary);
  }

  .stat-value.success { color: var(--success); }
  .stat-value.error { color: var(--error); }

  .card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
  }

  .card-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 1rem;
  }

  .empty-hint {
    font-size: 0.875rem;
    color: var(--text-muted);
  }

  .list-stack {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .list-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 1rem;
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
  }

  .list-row-label {
    font-size: 0.875rem;
    color: var(--text-primary);
  }

  .badge {
    font-size: 0.6875rem;
    font-family: monospace;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
  }

  .badge-success {
    background: rgba(63, 185, 80, 0.15);
    color: var(--success);
  }

  .badge-error {
    background: rgba(248, 81, 73, 0.15);
    color: var(--error);
  }

  .badge-warning {
    background: rgba(210, 153, 34, 0.15);
    color: var(--warning);
  }

  .badge-muted {
    background: transparent;
    color: var(--text-muted);
  }

  .audit-list {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .audit-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.375rem 0.75rem;
    font-size: 0.75rem;
    font-family: monospace;
    color: var(--text-secondary);
  }

  .audit-time {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .audit-action {
    color: var(--accent);
    white-space: nowrap;
  }

  .audit-resource {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .metrics-pre {
    font-size: 0.75rem;
    font-family: monospace;
    color: var(--text-muted);
    overflow-x: auto;
    max-height: 16rem;
    overflow-y: auto;
    padding: 0.5rem;
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
  }

  :global(.icon-accent) { color: var(--accent); }
  :global(.icon-muted) { color: var(--text-muted); }
  :global(.icon-error) { color: var(--error); }
  :global(.animate-spin) { animation: spin 1s linear infinite; }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @media (max-width: 768px) {
    .card-grid { grid-template-columns: repeat(2, 1fr); }
  }
</style>
