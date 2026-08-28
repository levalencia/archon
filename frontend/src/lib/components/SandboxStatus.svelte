<script lang="ts">
  import { onMount } from 'svelte';
  import { AlertTriangle, Box, CheckCircle2, Loader2, RefreshCw, ShieldOff } from 'lucide-svelte';
  import { getSandboxStatus, type SandboxStatus } from '$lib/sandbox';

  let status: SandboxStatus | null = $state(null);
  let loading = $state(true);
  let error = $state('');
  let requestVersion = 0;
  let destroyed = false;

  async function load() {
    const version = ++requestVersion;
    loading = true;
    error = '';
    try {
      const result = await getSandboxStatus();
      if (!destroyed && version === requestVersion) status = result;
    } catch (cause) {
      if (!destroyed && version === requestVersion) {
        error = cause instanceof Error ? cause.message : 'Sandbox status unavailable';
      }
    } finally {
      if (!destroyed && version === requestVersion) loading = false;
    }
  }

  const bytes = (value: number) => value >= 1024 ? `${Math.round(value / 1024)} KiB` : `${value} B`;

  onMount(() => {
    destroyed = false;
    void load();
    return () => {
      destroyed = true;
      ++requestVersion;
    };
  });
</script>

<section class="sandbox-card" aria-labelledby="sandbox-heading">
  <header>
    <div>
      <p class="eyebrow">Execution boundary</p>
      <h2 id="sandbox-heading"><Box size={17} /> Sandbox runner</h2>
    </div>
    <button onclick={load} disabled={loading} aria-label="Refresh sandbox status">
      <RefreshCw size={15} class={loading ? 'spin' : ''} /> Refresh
    </button>
  </header>

  {#if loading}
    <div class="state" aria-live="polite"><Loader2 size={19} class="spin" /> Checking isolated runner…</div>
  {:else if error}
    <div class="state error" role="alert"><AlertTriangle size={19} /><strong>Status unavailable</strong><span>{error}</span></div>
  {:else if status && !status.enabled}
    <div class="state"><ShieldOff size={20} /><strong>Execution disabled</strong><span>No execution tool is registered.</span></div>
  {:else if status}
    <div class="summary">
      <div class="availability" class:ready={status.available}>
        {#if status.available}<CheckCircle2 size={18} /> Runner available{:else}<AlertTriangle size={18} /> Runner unavailable{/if}
      </div>
      <dl>
        <div><dt>Isolation</dt><dd>{status.isolation}</dd></div>
        <div><dt>Network</dt><dd>{status.network_access ? 'Allowed' : 'Blocked'}</dd></div>
        <div><dt>Commands</dt><dd>{status.kinds.join(', ') || 'None'}</dd></div>
        <div><dt>Wall timeout</dt><dd>{status.timeout_seconds}s</dd></div>
        <div><dt>Output cap</dt><dd>{bytes(status.output_bytes)}</dd></div>
        <div><dt>Memory / PIDs</dt><dd>{status.memory_mb} MiB / {status.pids_limit}</dd></div>
        <div><dt>CPU limit</dt><dd>{status.cpus}</dd></div>
      </dl>
      <p>Commands require the normal tool-policy and approval boundary. No host or Docker socket is exposed.</p>
    </div>
  {/if}
</section>

<style>
  .sandbox-card{display:grid;gap:14px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:.75rem;padding:1.25rem;min-width:0}header{display:flex;align-items:center;justify-content:space-between;gap:12px}.eyebrow{margin:0;color:var(--text-muted);font-size:10px;text-transform:uppercase;letter-spacing:.09em}h2{display:flex;align-items:center;gap:7px;margin:2px 0 0;font-size:.9375rem}button{min-height:40px;display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:7px;background:var(--bg-tertiary);color:var(--text-primary);padding:7px 10px;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.state{min-height:96px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;text-align:center;color:var(--text-muted)}.state.error{color:var(--danger)}.summary{display:grid;gap:12px}.availability{display:flex;align-items:center;gap:7px;color:var(--danger);font-weight:600}.availability.ready{color:var(--success)}dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0}dl div{min-width:0;background:var(--bg-tertiary);border-radius:7px;padding:9px}dt{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--text-muted)}dd{margin:3px 0 0;font-size:12px;overflow-wrap:anywhere}.summary p{margin:0;color:var(--text-muted);font-size:11px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:640px){header{align-items:stretch;flex-direction:column}button{justify-content:center}dl{grid-template-columns:1fr}}
</style>
