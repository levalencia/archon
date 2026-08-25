<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  import { Shield, Zap, AlertTriangle, CheckCircle, XCircle, Loader, Play } from 'lucide-svelte';

  let redTeamResults: any = $state(null);
  let fuzzResults: any = $state(null);
  let running = $state('');

  async function runRedTeam() {
    running = 'redteam';
    try {
      const r = await authenticatedFetch('/api/eval/red-team', { method: 'POST' });
      redTeamResults = await r.json();
    } catch {
      redTeamResults = { error: 'Red team test failed' };
    }
    running = '';
  }

  async function runFuzz() {
    running = 'fuzz';
    try {
      const r = await authenticatedFetch('/api/eval/fuzz', { method: 'POST' });
      fuzzResults = await r.json();
    } catch {
      fuzzResults = { error: 'Fuzz test failed' };
    }
    running = '';
  }
</script>

<div class="page-container">
  <header class="page-header">
    <div class="page-title">
      <Shield size={22} strokeWidth={2} class="icon-accent" />
      <h1>Evaluation & Security</h1>
    </div>
  </header>

  <!-- Red Team Testing -->
  <section class="card">
    <div class="card-header">
      <h2 class="card-title">
        <AlertTriangle size={16} strokeWidth={2} class="icon-error" />
        Red Team Testing
      </h2>
      <button onclick={runRedTeam} disabled={running === 'redteam'} class="btn-danger">
        {#if running === 'redteam'}
          <Loader size={14} class="animate-spin" />
          Running...
        {:else}
          <Play size={14} />
          Run Red Team
        {/if}
      </button>
    </div>

    {#if redTeamResults?.error}
      <div class="error-msg">
        <XCircle size={14} />
        {redTeamResults.error}
      </div>
    {:else if redTeamResults}
      <div class="stat-row">
        <div class="stat-card-sm">
          <div class="stat-label">Total Prompts</div>
          <div class="stat-value">{redTeamResults.total_prompts}</div>
        </div>
        <div class="stat-card-sm">
          <div class="stat-label">Blocked</div>
          <div class="stat-value success">{redTeamResults.blocked}</div>
        </div>
        <div class="stat-card-sm">
          <div class="stat-label">Block Rate</div>
          <div class="stat-value" class:success={redTeamResults.block_rate >= 0.8} class:error={redTeamResults.block_rate < 0.8}>
            {Math.round(redTeamResults.block_rate * 100)}%
          </div>
        </div>
      </div>

      {#if redTeamResults.results?.length > 0}
        <div class="results-table">
          <div class="table-header">
            <span class="col-status">Status</span>
            <span class="col-prompt">Prompt</span>
            <span class="col-rules">Triggered Rules</span>
          </div>
          <div class="table-body">
            {#each redTeamResults.results as r}
              <div class="table-row">
                <span class="col-status">
                  {#if r.blocked}
                    <CheckCircle size={14} class="icon-success" />
                  {:else}
                    <XCircle size={14} class="icon-error" />
                  {/if}
                </span>
                <span class="col-prompt" title={r.prompt}>{r.prompt}</span>
                <span class="col-rules">{r.triggered_rules?.join(', ') || '—'}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </section>

  <!-- Fuzz Testing -->
  <section class="card">
    <div class="card-header">
      <h2 class="card-title">
        <Zap size={16} strokeWidth={2} class="icon-warning" />
        Fuzz Testing
      </h2>
      <button onclick={runFuzz} disabled={running === 'fuzz'} class="btn-warning">
        {#if running === 'fuzz'}
          <Loader size={14} class="animate-spin" />
          Running...
        {:else}
          <Play size={14} />
          Run Fuzz (50 inputs)
        {/if}
      </button>
    </div>

    {#if fuzzResults?.error}
      <div class="error-msg">
        <XCircle size={14} />
        {fuzzResults.error}
      </div>
    {:else if fuzzResults}
      <div class="stat-row">
        <div class="stat-card-sm">
          <div class="stat-label">Total Inputs</div>
          <div class="stat-value">{fuzzResults.total_inputs}</div>
        </div>
        <div class="stat-card-sm">
          <div class="stat-label">Crashes</div>
          <div class="stat-value" class:success={fuzzResults.crashes === 0} class:error={fuzzResults.crashes > 0}>
            {fuzzResults.crashes}
          </div>
        </div>
        <div class="stat-card-sm">
          <div class="stat-label">Unexpected</div>
          <div class="stat-value warning">{fuzzResults.unexpected}</div>
        </div>
      </div>

      {#if fuzzResults.results?.length > 0}
        <div class="results-table">
          <div class="table-header">
            <span class="col-status">Status</span>
            <span class="col-prompt">Input</span>
            <span class="col-rules">Response</span>
          </div>
          <div class="table-body">
            {#each fuzzResults.results as r}
              <div class="table-row">
                <span class="col-status">
                  {#if r.status === 'ok'}
                    <CheckCircle size={14} class="icon-success" />
                  {:else if r.status === 'crash'}
                    <XCircle size={14} class="icon-error" />
                  {:else}
                    <AlertTriangle size={14} class="icon-warning" />
                  {/if}
                </span>
                <span class="col-prompt" title={r.input}>{r.input}</span>
                <span class="col-rules">{r.response || r.error || '—'}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </section>
</div>

<style>
  .page-container {
    max-width: 64rem;
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

  .card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
  }

  .card-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--text-primary);
    margin: 0;
  }

  /* Buttons */
  .btn-danger,
  .btn-warning {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 1rem;
    color: white;
    border: none;
    border-radius: 0.5rem;
    font-size: 0.8125rem;
    cursor: pointer;
    transition: opacity 0.15s;
    white-space: nowrap;
  }

  .btn-danger { background: var(--error); }
  .btn-warning { background: var(--warning); }

  .btn-danger:hover:not(:disabled),
  .btn-warning:hover:not(:disabled) { opacity: 0.85; }

  .btn-danger:disabled,
  .btn-warning:disabled { opacity: 0.5; cursor: not-allowed; }

  .error-msg {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: rgba(248, 81, 73, 0.1);
    border-radius: 0.5rem;
    font-size: 0.8125rem;
    color: var(--error);
  }

  /* Stats */
  .stat-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .stat-card-sm {
    padding: 0.75rem;
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
  }

  .stat-label {
    font-size: 0.6875rem;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.025em;
    margin-bottom: 0.25rem;
  }

  .stat-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text-primary);
  }

  .stat-value.success { color: var(--success); }
  .stat-value.error { color: var(--error); }
  .stat-value.warning { color: var(--warning); }

  /* Results Table */
  .results-table {
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    overflow: hidden;
  }

  .table-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    background: var(--bg-tertiary);
    font-size: 0.6875rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .table-body {
    max-height: 20rem;
    overflow-y: auto;
  }

  .table-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    border-top: 1px solid var(--border);
    transition: background 0.1s;
  }

  .table-row:hover {
    background: var(--bg-hover);
  }

  .col-status {
    flex-shrink: 0;
    width: 2.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .col-prompt {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: monospace;
  }

  .col-rules {
    flex-shrink: 0;
    width: 10rem;
    font-family: monospace;
    font-size: 0.6875rem;
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  :global(.icon-accent) { color: var(--accent); }
  :global(.icon-success) { color: var(--success); }
  :global(.icon-error) { color: var(--error); }
  :global(.icon-warning) { color: var(--warning); }
  :global(.icon-muted) { color: var(--text-muted); }
  :global(.animate-spin) { animation: spin 1s linear infinite; }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
