<script lang="ts">
  import { onMount } from 'svelte';
  import { authenticatedFetch } from '$lib/auth';
  import {
    compareEvaluations, createEvaluation, getEvaluation, listEvaluations, listRecordedRuns,
    type Evaluation, type EvaluationComparison,
  } from '$lib/evaluations';
  import type { Run } from '$lib/runs';
  import { Shield, Zap, AlertTriangle, CheckCircle, XCircle, Loader, Play, History, GitCompare, FileCheck } from 'lucide-svelte';

  let runs: Run[] = $state([]);
  let evaluations: Evaluation[] = $state([]);
  let selected: Evaluation | null = $state(null);
  let comparison: EvaluationComparison | null = $state(null);
  let groundedRunId = $state('');
  let abstentionRunId = $state('');
  let projectId = $state('');
  let threshold = $state(0.85);
  let compareA = $state('');
  let compareB = $state('');
  let loading = $state(true);
  let creating = $state(false);
  let reportLoading = $state(false);
  let comparing = $state(false);
  let error = $state('');

  let redTeamResults: any = $state(null);
  let fuzzResults: any = $state(null);
  let securityRunning = $state('');

  const runLabel = (run: Run) => `${run.model || run.provider} · ${run.answer_summary || run.run_id}`;
  const percent = (value: unknown) => `${Math.round((typeof value === 'number' ? value : 0) * 100)}%`;
  const number = (value: unknown, digits = 2) => typeof value === 'number' ? value.toFixed(digits).replace(/\.00$/, '') : '—';
  const shortId = (id: string) => id.length > 14 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
  const date = (value: string | null) => value ? new Date(value).toLocaleString() : 'Pending';
  const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : 'Evaluation request failed';

  function chooseDefaults() {
    if (!projectId && runs[0]) projectId = runs[0].project_id;
    const eligible = runs.filter((run) => !projectId || run.project_id === projectId);
    if (!eligible.some((run) => run.run_id === groundedRunId)) groundedRunId = eligible[0]?.run_id || '';
    if (!eligible.some((run) => run.run_id === abstentionRunId) || abstentionRunId === groundedRunId) {
      abstentionRunId = eligible.find((run) => run.run_id !== groundedRunId)?.run_id || '';
    }
  }

  async function load() {
    loading = true; error = '';
    try {
      [runs, evaluations] = await Promise.all([listRecordedRuns(), listEvaluations()]);
      chooseDefaults();
      compareA = evaluations[0]?.id || '';
      compareB = evaluations.find((item) => item.id !== compareA)?.id || '';
    } catch (cause) { error = errorMessage(cause); }
    finally { loading = false; }
  }

  async function runEvaluation() {
    if (!projectId || !groundedRunId || !abstentionRunId || groundedRunId === abstentionRunId) return;
    creating = true; error = ''; comparison = null;
    try {
      const result = await createEvaluation({ projectId, threshold, groundedCitationRunId: groundedRunId, safeAbstentionRunId: abstentionRunId });
      evaluations = [result, ...evaluations.filter((item) => item.id !== result.id)];
      selected = result;
      compareA = result.id;
      compareB ||= evaluations.find((item) => item.id !== result.id)?.id || '';
    } catch (cause) { error = errorMessage(cause); }
    finally { creating = false; }
  }

  async function showReport(id: string) {
    reportLoading = true; error = ''; comparison = null;
    try { selected = await getEvaluation(id); }
    catch (cause) { error = errorMessage(cause); }
    finally { reportLoading = false; }
  }

  async function runComparison() {
    if (!compareA || !compareB || compareA === compareB) return;
    comparing = true; error = '';
    try { comparison = await compareEvaluations(compareA, compareB); }
    catch (cause) { error = errorMessage(cause); }
    finally { comparing = false; }
  }

  async function runSecurity(kind: 'redteam' | 'fuzz') {
    securityRunning = kind;
    try {
      const response = await authenticatedFetch(kind === 'redteam' ? '/api/security/red-team' : '/api/security/fuzz', { method: 'POST' });
      if (!response.ok) throw new Error(`${kind === 'redteam' ? 'Red team' : 'Fuzz'} test failed`);
      if (kind === 'redteam') redTeamResults = await response.json(); else fuzzResults = await response.json();
    } catch (cause) {
      const result = { error: errorMessage(cause) };
      if (kind === 'redteam') redTeamResults = result; else fuzzResults = result;
    } finally { securityRunning = ''; }
  }

  onMount(load);
</script>

<svelte:head><title>Recorded Run Evaluations · Archon</title></svelte:head>

<div class="page-container">
  <header class="page-header">
    <div><p class="eyebrow">Deterministic quality gates</p><h1>Recorded Run Evaluations</h1><p>Score completed, persisted runs without invoking a model, chat, retriever, or tool.</p></div>
    <button class="btn-secondary" onclick={load} disabled={loading} aria-label="Reload evaluations">{#if loading}<Loader size={15} class="animate-spin" />{:else}<History size={15} />{/if} Refresh</button>
  </header>

  {#if error}<div class="error-msg" role="alert"><XCircle size={16} /> <span>{error}</span></div>{/if}

  <section class="card setup" aria-labelledby="new-evaluation-heading">
    <div class="section-heading"><div><p class="eyebrow">grounded-v1</p><h2 id="new-evaluation-heading">Create evaluation</h2></div><span class="dataset-tag">2 recorded cases</span></div>
    {#if loading}
      <div class="loading-state" aria-label="Loading recorded runs"><Loader size={20} class="animate-spin" /> Loading completed runs…</div>
    {:else if runs.length === 0}
      <div class="empty-state"><History size={24} /><strong>No completed recorded runs</strong><span>Complete at least two runs to evaluate grounded citation and safe abstention.</span></div>
    {:else}
      <div class="form-grid">
        <label>Project<select bind:value={projectId} onchange={chooseDefaults}>{#each [...new Set(runs.map((run) => run.project_id))] as project}<option value={project}>{project}</option>{/each}</select></label>
        <label>Pass threshold<div class="threshold"><input aria-label="Pass threshold" type="range" min="0" max="1" step="0.05" bind:value={threshold} /><output>{percent(threshold)}</output></div></label>
        <label>Grounded citation run<select aria-label="Grounded citation run" bind:value={groundedRunId}>{#each runs.filter((run) => run.project_id === projectId) as run}<option value={run.run_id}>{runLabel(run)}</option>{/each}</select><small>grounded-citation</small></label>
        <label>Safe abstention run<select aria-label="Safe abstention run" bind:value={abstentionRunId}>{#each runs.filter((run) => run.project_id === projectId) as run}<option value={run.run_id}>{runLabel(run)}</option>{/each}</select><small>safe-abstention</small></label>
      </div>
      {#if groundedRunId && groundedRunId === abstentionRunId}<p class="inline-warning" role="alert">Choose two distinct recorded runs.</p>{/if}
      <button class="btn-primary" onclick={runEvaluation} disabled={creating || !groundedRunId || !abstentionRunId || groundedRunId === abstentionRunId}>
        {#if creating}<Loader size={15} class="animate-spin" /> Evaluating…{:else}<Play size={15} /> Run recorded evaluation{/if}
      </button>
    {/if}
  </section>

  <section class="card" aria-labelledby="history-heading">
    <div class="section-heading"><div><p class="eyebrow">Durable results</p><h2 id="history-heading">Evaluation history</h2></div><span class="count">{evaluations.length}</span></div>
    {#if !loading && evaluations.length === 0}<div class="empty-state compact"><FileCheck size={22} /><strong>No evaluation history yet</strong><span>Your recorded evaluation reports will appear here.</span></div>{/if}
    <div class="history-grid">
      {#each evaluations as item}
        <button class:selected={selected?.id === item.id} class="history-card" onclick={() => showReport(item.id)} aria-label={`Open evaluation ${item.id}`}>
          <div class="history-top"><span class:pass={item.passed === true} class:fail={item.passed === false} class="status">{item.status}{item.status === 'completed' ? ` · ${item.passed ? 'passed' : 'failed'}` : ''}</span><time>{date(item.created_at)}</time></div>
          <strong>{item.project_id}</strong><code>{shortId(item.id)}</code>
          <dl><div><dt>Pass rate</dt><dd>{percent(item.aggregate_metrics.pass_rate)}</dd></div><div><dt>Mean score</dt><dd>{number(item.aggregate_metrics.mean_score)}</dd></div><div><dt>Dataset</dt><dd>{item.dataset_version}</dd></div></dl>
        </button>
      {/each}
    </div>
  </section>

  {#if reportLoading}<section class="card loading-state"><Loader size={20} class="animate-spin" /> Loading report…</section>{/if}
  {#if selected && !reportLoading}
    <section class="card report" aria-labelledby="report-heading">
      <div class="section-heading"><div><p class="eyebrow">Evaluation report</p><h2 id="report-heading">{selected.project_id} <code>{shortId(selected.id)}</code></h2></div><span class:pass={selected.passed === true} class:fail={selected.passed === false} class="gate">{selected.passed ? 'Gate passed' : 'Gate failed'}</span></div>
      <div class="summary-grid"><div><span>Mean score</span><strong>{number(selected.aggregate_metrics.mean_score)}</strong></div><div><span>Pass rate</span><strong>{percent(selected.aggregate_metrics.pass_rate)}</strong></div><div><span>Threshold</span><strong>{percent(selected.threshold)}</strong></div><div><span>Dataset</span><strong>{selected.dataset_id} · {selected.dataset_version}</strong></div></div>
      <div class="case-list">
        {#each selected.cases as item}
          <article class="case-row">
            <header><div>{#if item.passed}<CheckCircle size={17} class="icon-success" />{:else}<XCircle size={17} class="icon-error" />{/if}<strong>{item.case_key}</strong></div><code>{shortId(item.source_run_id)}</code></header>
            <div class="metric-list">{#each Object.entries(item.metrics) as [name, value]}<span><small>{name.replaceAll('_', ' ')}</small><b>{number(value)}</b></span>{/each}</div>
            <ul class="checks">{#each item.checks as check}<li class:failed={!check.passed}>{check.passed ? '✓' : '×'} {check.name.replaceAll('_', ' ')}</li>{/each}</ul>
          </article>
        {/each}
        {#if selected.cases.length === 0}<p class="muted">Case details are unavailable for this report.</p>{/if}
      </div>
    </section>
  {/if}

  <section class="card" aria-labelledby="compare-heading">
    <div class="section-heading"><div><p class="eyebrow">Regression view</p><h2 id="compare-heading"><GitCompare size={17} /> Compare evaluations</h2></div></div>
    <div class="compare-controls"><label>Baseline<select aria-label="Baseline evaluation" bind:value={compareA}><option value="">Select baseline</option>{#each evaluations as item}<option value={item.id}>{item.project_id} · {shortId(item.id)}</option>{/each}</select></label><label>Candidate<select aria-label="Candidate evaluation" bind:value={compareB}><option value="">Select candidate</option>{#each evaluations as item}<option value={item.id}>{item.project_id} · {shortId(item.id)}</option>{/each}</select></label><button class="btn-secondary" onclick={runComparison} disabled={comparing || !compareA || !compareB || compareA === compareB}>{#if comparing}<Loader size={15} class="animate-spin" />{:else}<GitCompare size={15} />{/if} Compare</button></div>
    {#if comparison}<div class="delta-grid" aria-label="Evaluation deltas">{#each Object.entries(comparison.metric_delta_b_minus_a) as [name, value]}<div><span>{name.replaceAll('_', ' ')}</span><strong class:positive={value > 0} class:negative={value < 0}>{value > 0 ? '+' : ''}{number(value)}</strong><small>candidate − baseline</small></div>{/each}</div>{/if}
  </section>

  <div class="security-divider"><span>Separate security testing</span></div>
  <section class="security-grid" aria-label="Security testing">
    <article class="card security-card"><div class="section-heading"><h2><AlertTriangle size={17} class="icon-error" /> Red Team Testing</h2><button class="btn-danger" onclick={() => runSecurity('redteam')} disabled={securityRunning === 'redteam'}>{securityRunning === 'redteam' ? 'Running…' : 'Run red team'}</button></div>{#if redTeamResults?.error}<div class="error-msg">{redTeamResults.error}</div>{:else if redTeamResults}<p>{redTeamResults.blocked} of {redTeamResults.total_prompts} prompts blocked ({percent(redTeamResults.block_rate)}).</p>{:else}<p>Probe policy controls with adversarial prompts. This is not part of recorded-run scoring.</p>{/if}</article>
    <article class="card security-card"><div class="section-heading"><h2><Zap size={17} class="icon-warning" /> Fuzz Testing</h2><button class="btn-warning" onclick={() => runSecurity('fuzz')} disabled={securityRunning === 'fuzz'}>{securityRunning === 'fuzz' ? 'Running…' : 'Run fuzz'}</button></div>{#if fuzzResults?.error}<div class="error-msg">{fuzzResults.error}</div>{:else if fuzzResults}<p>{fuzzResults.total_inputs} inputs · {fuzzResults.crashes} crashes · {fuzzResults.unexpected} unexpected.</p>{:else}<p>Exercise input handling independently from evaluation reports.</p>{/if}</article>
  </section>
</div>

<style>
  .page-container{max-width:76rem;margin:0 auto;padding:1.75rem;display:flex;flex-direction:column;gap:1.25rem;min-width:0}.page-header,.section-heading,.history-top,.case-row header{display:flex;align-items:center;justify-content:space-between;gap:1rem}.page-header h1{font-size:1.65rem;margin:.2rem 0;color:var(--text-primary)}.page-header p:last-child,.security-card p,.muted{color:var(--text-muted);font-size:.85rem;margin:.2rem 0}.eyebrow{margin:0;color:var(--accent);font-size:.66rem;text-transform:uppercase;letter-spacing:.12em;font-weight:750}.card{background:var(--bg-secondary);border:1px solid var(--border);border-radius:.8rem;padding:1.2rem;min-width:0}.section-heading{margin-bottom:1rem}.section-heading h2{display:flex;align-items:center;gap:.45rem;font-size:1rem;margin:.2rem 0;color:var(--text-primary)}.dataset-tag,.count{border:1px solid var(--border);background:var(--bg-tertiary);padding:.3rem .55rem;border-radius:999px;color:var(--text-secondary);font-size:.7rem}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem;margin-bottom:1rem}label{display:flex;flex-direction:column;gap:.4rem;color:var(--text-secondary);font-size:.73rem;font-weight:650}select,input{width:100%;min-height:44px;border:1px solid var(--border);border-radius:.5rem;background:var(--bg-tertiary);color:var(--text-primary);padding:0 .7rem}input[type=range]{min-height:44px;padding:0}.threshold{display:flex;align-items:center;gap:.65rem}.threshold output{min-width:2.5rem;color:var(--accent);font-weight:750}label small{font-family:var(--font-mono);color:var(--text-muted)}button{border:0;cursor:pointer}.btn-primary,.btn-secondary,.btn-danger,.btn-warning{display:inline-flex;align-items:center;justify-content:center;gap:.4rem;border-radius:.5rem;padding:.35rem .85rem;font-size:.78rem;font-weight:700}.btn-primary{background:var(--accent);color:#07110f}.btn-secondary{background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border)}.btn-danger{background:var(--error);color:#fff}.btn-warning{background:var(--warning);color:#15100a}.btn-primary:disabled,.btn-secondary:disabled,.btn-danger:disabled,.btn-warning:disabled{opacity:.45;cursor:not-allowed}.error-msg,.inline-warning{display:flex;align-items:center;gap:.5rem;color:var(--error);background:rgba(255,107,114,.09);border:1px solid rgba(255,107,114,.22);border-radius:.5rem;padding:.7rem;font-size:.8rem}.inline-warning{margin:0 0 1rem}.loading-state,.empty-state{min-height:7rem;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:.45rem;color:var(--text-muted);text-align:center;font-size:.8rem}.empty-state strong{color:var(--text-primary)}.empty-state.compact{min-height:5rem}.history-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem}.history-card{text-align:left;padding:.85rem;border-radius:.65rem;border:1px solid var(--border);background:var(--bg-tertiary);color:var(--text-primary);min-width:0}.history-card:hover,.history-card.selected{border-color:var(--accent)}.history-top time{font-size:.65rem;color:var(--text-muted)}.status,.gate{font-size:.65rem;text-transform:uppercase;color:var(--warning);font-weight:800}.pass{color:var(--success)!important}.fail,.failed{color:var(--error)!important}.history-card>strong,.history-card>code{display:block;margin-top:.45rem}.history-card>code,.case-row code,.report h2 code{font-size:.68rem;color:var(--text-muted)}dl{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin:.8rem 0 0}dt,.summary-grid span,.delta-grid span{font-size:.62rem;text-transform:uppercase;color:var(--text-muted)}dd{margin:.15rem 0 0;font-weight:700}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.65rem;margin-bottom:1rem}.summary-grid>div,.delta-grid>div{background:var(--bg-tertiary);padding:.75rem;border-radius:.55rem;display:flex;flex-direction:column;gap:.25rem}.summary-grid strong{font-size:.9rem}.case-list{display:flex;flex-direction:column;gap:.65rem}.case-row{border:1px solid var(--border);border-radius:.6rem;padding:.85rem}.case-row header>div{display:flex;align-items:center;gap:.45rem}.metric-list{display:flex;flex-wrap:wrap;gap:.5rem;margin:.75rem 0}.metric-list span{background:var(--bg-tertiary);padding:.4rem .55rem;border-radius:.4rem;display:flex;gap:.5rem}.metric-list small{color:var(--text-muted)}.checks{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;padding:0;margin:0}.checks li{font-size:.7rem;color:var(--success);border:1px solid currentColor;border-radius:999px;padding:.2rem .45rem}.compare-controls{display:grid;grid-template-columns:1fr 1fr auto;gap:.75rem;align-items:end}.delta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr));gap:.6rem;margin-top:1rem}.delta-grid strong{font-size:1.15rem}.delta-grid small{color:var(--text-muted);font-size:.6rem}.positive{color:var(--success)}.negative{color:var(--error)}.security-divider{display:flex;align-items:center;gap:1rem;color:var(--text-muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.1em}.security-divider:before,.security-divider:after{content:'';height:1px;background:var(--border);flex:1}.security-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.security-card{border-style:dashed}.security-card .section-heading{margin-bottom:.5rem}:global(.icon-success){color:var(--success)}:global(.icon-error){color:var(--error)}:global(.icon-warning){color:var(--warning)}:global(.animate-spin){animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  @media(max-width:700px){.page-container{padding:1rem;gap:1rem}.page-header{align-items:flex-start}.page-header h1{font-size:1.35rem}.page-header>div{min-width:0}.page-header .btn-secondary{font-size:0;padding:.35rem;width:44px;flex:0 0 44px}.form-grid,.history-grid,.security-grid,.summary-grid{grid-template-columns:1fr}.compare-controls{grid-template-columns:1fr}.compare-controls button,.btn-primary{width:100%}.history-card{min-height:0}.section-heading{align-items:flex-start}.case-row header{align-items:flex-start;flex-direction:column}.summary-grid{grid-template-columns:repeat(2,1fr)}dl{gap:.25rem}.security-card .section-heading{flex-direction:column}.security-card button{width:100%}}
</style>
