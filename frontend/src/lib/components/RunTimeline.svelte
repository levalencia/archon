<script lang="ts">
 import { compareRuns, getRun, getRunEvents, listRuns, type ComparedRun, type Run, type RunEvent } from '$lib/runs';
 import RunSummary from './RunSummary.svelte';
 import RunExportPanel from './RunExportPanel.svelte';
 let { conversationId, onFork = (_id: string) => {} }: { conversationId: string; onFork?: (id: string) => void } = $props();
 let runs: Run[] = $state([]); let selected: Run | null = $state(null); let events: RunEvent[] = $state([]);
 let compareId = $state(''); let comparison: {a: ComparedRun;b: ComparedRun}|null = $state(null); let loading=$state(false); let error=$state('');
 async function select(id: string) { loading=true; error=''; try { [selected, events] = await Promise.all([getRun(id), getRunEvents(id)]); comparison=null; } catch(e){error=e instanceof Error?e.message:'Run unavailable'} finally{loading=false} }
 async function refresh() { if(!conversationId){runs=[];selected=null;return} loading=true; try { runs=await listRuns({conversationId}); if(runs[0]) await select(runs[0].run_id); else selected=null; } catch(e){error=e instanceof Error?e.message:'Runs unavailable'} finally{loading=false} }
 async function compare(){if(!selected||!compareId)return;try{comparison=await compareRuns(selected.run_id,compareId)}catch(e){error=e instanceof Error?e.message:'Comparison failed'}}
 $effect(()=>{conversationId; void refresh()});
</script>
<div class="timeline">
 <div class="toolbar"><strong>Run timeline</strong><button onclick={refresh} disabled={loading}>Reload</button></div>
 {#if error}<p role="alert">{error}</p>{/if}
 {#if runs.length}
  <label>Run <select value={selected?.run_id || ''} onchange={(e)=>select(e.currentTarget.value)}>{#each runs as run}<option value={run.run_id}>{new Date(run.started_at).toLocaleString()} · {run.status}</option>{/each}</select></label>
  {#if selected}<RunSummary run={selected} {events} {onFork}/><RunExportPanel runId={selected.run_id}/>{/if}
  <ol>{#each events as event}<li><span>#{event.sequence}</span><strong>{event.kind.replaceAll('_',' ')}</strong><small>iteration {event.iteration}</small><code>{Object.entries(event.payload).map(([k,v])=>`${k}: ${String(v)}`).join(' · ') || 'No persisted payload'}</code></li>{/each}</ol>
  {#if runs.length > 1}<div class="compare"><select bind:value={compareId}><option value="">Compare with…</option>{#each runs.filter(r=>r.run_id!==selected?.run_id) as run}<option value={run.run_id}>{new Date(run.started_at).toLocaleString()}</option>{/each}</select><button disabled={!compareId} onclick={compare}>Compare</button></div>{/if}
  {#if comparison}<div class="comparison"><h3>Stored run comparison</h3><table><thead><tr><th>Metric</th><th>A</th><th>B</th></tr></thead><tbody>{#each [['Model',comparison.a.model,comparison.b.model],['Tokens',comparison.a.tokens.total,comparison.b.tokens.total],['Latency',comparison.a.latency_ms??'Not recorded',comparison.b.latency_ms??'Not recorded'],['Iterations',comparison.a.iterations,comparison.b.iterations],['Stop',comparison.a.stop_reason??'Not recorded',comparison.b.stop_reason??'Not recorded']] as row}<tr><th>{row[0]}</th><td>{row[1]}</td><td>{row[2]}</td></tr>{/each}</tbody></table></div>{/if}
 {:else if !loading}<p class="empty">No persisted runs for this conversation.</p>{/if}
</div>
<style>
.timeline{display:grid;gap:12px}.toolbar,.compare{display:flex;gap:8px;justify-content:space-between;align-items:center}button,select{border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:6px;padding:6px;max-width:100%}label{display:grid;gap:4px;font-size:11px;color:var(--muted)}ol{list-style:none;padding:0;margin:0;display:grid;gap:6px;max-height:280px;overflow:auto}li{display:grid;grid-template-columns:auto 1fr auto;gap:6px;border-left:2px solid var(--accent);padding:7px;background:var(--surface);font-size:10px}li code{grid-column:2/4;white-space:normal;overflow-wrap:anywhere;color:var(--muted)}table{width:100%;font-size:10px;border-collapse:collapse}td,th{text-align:left;padding:5px;border-bottom:1px solid var(--border);overflow-wrap:anywhere}.empty,[role=alert]{font-size:11px;color:var(--muted)}@media(max-width:720px){.compare{align-items:stretch;flex-direction:column}}
</style>
