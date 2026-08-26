<script lang="ts">
  import type { Run, RunEvent } from '$lib/runs';
  import { forkRun } from '$lib/runs';
  let { run, events = [], onFork = (_id: string) => {} }: { run: Run; events?: RunEvent[]; onFork?: (id: string) => void } = $props();
  let busy = $state(false); let error = $state('');
  async function fork() {
    const sequence = events.at(-1)?.sequence;
    if (!sequence) return;
    busy = true; error = '';
    try { const result = await forkRun(run.run_id, sequence); onFork(result.target_conversation_id); }
    catch (e) { error = e instanceof Error ? e.message : 'Fork failed'; }
    finally { busy = false; }
  }
</script>
<section class="run-summary" aria-label="Persisted run summary">
  <div class="summary-head"><div><small>Persisted run</small><strong>{run.status}</strong></div><button onclick={fork} disabled={busy || !events.length}>{busy ? 'Forking…' : 'Fork from latest event'}</button></div>
  {#if error}<p role="alert">{error}</p>{/if}
  <p class="answer">{run.answer_summary || 'Answer summary not available'}</p>
  <dl>
    <div><dt>Provider / model</dt><dd>{run.provider} / {run.model}</dd></div>
    <div><dt>Tokens</dt><dd>{run.total_tokens.toLocaleString()} ({run.input_tokens} in / {run.output_tokens} out)</dd></div>
    <div><dt>Cost</dt><dd>{run.cost_usd == null ? 'Not recorded' : `$${run.cost_usd.toFixed(4)}`}</dd></div>
    <div><dt>Latency</dt><dd>{run.latency_ms == null ? 'Not recorded' : `${Math.round(run.latency_ms)}ms`}</dd></div>
    <div><dt>Iterations</dt><dd>{run.iterations}</dd></div><div><dt>Stop reason</dt><dd>{run.stop_reason || 'Not recorded'}</dd></div>
    <div><dt>Workspace</dt><dd>Not restored (ephemeral sandbox)</dd></div>
    <div><dt>Memory/context</dt><dd>Not restored</dd></div>
  </dl>
</section>
<style>
.run-summary{display:grid;gap:12px}.summary-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.summary-head div{display:grid}.summary-head small,dt{color:var(--muted);font-size:11px}.summary-head button{border:1px solid var(--border);background:var(--surface);color:var(--text);padding:7px;border-radius:7px}.answer{font-size:12px;line-height:1.45;max-height:8em;overflow:auto}dl{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0}dl div{background:var(--surface);padding:8px;border-radius:7px}dd{margin:3px 0 0;font-size:11px;overflow-wrap:anywhere}@media(max-width:720px){dl{grid-template-columns:1fr}.summary-head{align-items:flex-start;flex-direction:column}}
</style>
