<script lang="ts">
  import { AlertTriangle, CheckCircle, GitCompare, Loader, RefreshCw, TrendingUp } from 'lucide-svelte';
  import {
    createCandidate, createDriftReport, decideCandidateApproval, getDriftReport,
    isInsufficientSample, listCandidates, transitionCandidate, type CandidateAction,
    type CandidateApprovalReceipt, type CandidateType, type DriftReport, type Evaluation,
    type OptimizationCandidate,
  } from '$lib/evaluations';

  let { projectId, evaluations }: { projectId: string; evaluations: Evaluation[] } = $props();
  let baselineId = $state('');
  let candidateEvalId = $state('');
  let minimumSampleSize = $state(20);
  let report = $state<DriftReport | null>(null);
  let reportId = $state('');
  let driftBusy = $state(false);
  let candidates = $state<OptimizationCandidate[]>([]);
  let candidateBusy = $state(false);
  let loadingCandidates = $state(false);
  let error = $state('');
  let candidateType = $state<CandidateType>('prompt');
  let changeSummary = $state('');
  let rollbackPlan = $state('');
  let targetRevision = $state('');
  let actionBusy = $state<Record<string, boolean>>({});
  let approvalReceipts = $state<Record<string, CandidateApprovalReceipt>>({});
  let approvalDecided = $state<Record<string, boolean>>({});
  let reasonCodes = $state<Record<string, string>>({});
  let promotionConfirmed = $state<Record<string, boolean>>({});
  let loadSequence = 0;
  let loadController: AbortController | null = null;
  let driftSequence = 0;
  let driftController: AbortController | null = null;
  let comparedCohortKey = $state('');
  let pendingDriftCohortKey = $state('');
  let candidateSequence = 0;

  const projectEvaluations = $derived(evaluations.filter((item) => item.project_id === projectId));
  const cohortKey = $derived(`${projectId}\u0000${baselineId}\u0000${candidateEvalId}`);
  const message = (cause: unknown) => cause instanceof Error ? cause.message : 'Review request failed';
  const display = (value: unknown) => typeof value === 'number' ? value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : value == null ? '—' : String(value);
  const label = (value: string) => value.replaceAll('_', ' ');
  const validReason = (value: string | undefined) => /^[a-z][a-z0-9_]{0,63}$/.test(value || '');

  $effect(() => {
    const items = projectEvaluations;
    if (!items.some((item) => item.id === baselineId)) baselineId = items[1]?.id || items[0]?.id || '';
    if (!items.some((item) => item.id === candidateEvalId) || candidateEvalId === baselineId) candidateEvalId = items.find((item) => item.id !== baselineId)?.id || '';
  });

  $effect(() => {
    const project = projectId;
    report = null; reportId = ''; candidates = []; comparedCohortKey = ''; pendingDriftCohortKey = '';
    driftController?.abort(); ++driftSequence; driftBusy = false;
    ++candidateSequence; candidateBusy = false;
    if (project) void loadCandidates(project);
    return () => { loadController?.abort(); driftController?.abort(); };
  });

  $effect(() => {
    const key = cohortKey;
    if (pendingDriftCohortKey && pendingDriftCohortKey !== key) {
      driftController?.abort();
      ++driftSequence;
      pendingDriftCohortKey = '';
      driftBusy = false;
    }
    if (comparedCohortKey && comparedCohortKey !== key) {
      report = null;
      reportId = '';
      comparedCohortKey = '';
      driftController?.abort();
      ++driftSequence;
      driftBusy = false;
    }
  });

  async function loadCandidates(project = projectId, clearError = true) {
    const sequence = ++loadSequence;
    loadController?.abort();
    const controller = new AbortController(); loadController = controller;
    loadingCandidates = true; if (clearError) error = '';
    try {
      const result = await listCandidates(project, controller.signal);
      if (sequence === loadSequence && project === projectId) candidates = result;
    } catch (cause) {
      if (clearError && !controller.signal.aborted && sequence === loadSequence) error = message(cause);
    } finally { if (sequence === loadSequence) loadingCandidates = false; }
  }

  async function compareDrift() {
    if (!projectId || !baselineId || !candidateEvalId || baselineId === candidateEvalId) return;
    const sequence = ++driftSequence;
    driftController?.abort();
    const controller = new AbortController(); driftController = controller;
    driftBusy = true; error = '';
    const snapshot = {
      project: projectId,
      baseline: baselineId,
      candidate: candidateEvalId,
      minimumSampleSize,
      cohortKey,
    };
    pendingDriftCohortKey = snapshot.cohortKey;
    try {
      const result = await createDriftReport({
        projectId: snapshot.project,
        baselineEvalId: snapshot.baseline,
        candidateEvalId: snapshot.candidate,
        minimumSampleSize: snapshot.minimumSampleSize,
      }, controller.signal);
      if (sequence === driftSequence && !controller.signal.aborted && snapshot.cohortKey === cohortKey) {
        report = result; reportId = result.id; comparedCohortKey = snapshot.cohortKey;
      }
    } catch (cause) {
      if (sequence === driftSequence && !controller.signal.aborted && snapshot.cohortKey === cohortKey) error = message(cause);
    } finally {
      if (sequence === driftSequence) {
        pendingDriftCohortKey = '';
        driftBusy = false;
      }
    }
  }

  async function openReport() {
    if (!reportId.trim() || !projectId) return;
    const sequence = ++driftSequence;
    driftController?.abort();
    const controller = new AbortController(); driftController = controller;
    driftBusy = true; error = '';
    const snapshot = { id: reportId.trim(), project: projectId };
    try {
      const result = await getDriftReport(snapshot.id, snapshot.project, controller.signal);
      if (sequence !== driftSequence || controller.signal.aborted || snapshot.project !== projectId || snapshot.id !== reportId.trim()) return;
      const pairExists = projectEvaluations.some((item) => item.id === result.baseline_eval_id)
        && projectEvaluations.some((item) => item.id === result.candidate_eval_id);
      const resultKey = `${snapshot.project}\u0000${result.baseline_eval_id}\u0000${result.candidate_eval_id}`;
      if (pairExists) {
        baselineId = result.baseline_eval_id;
        candidateEvalId = result.candidate_eval_id;
      }
      report = result;
      comparedCohortKey = resultKey;
    } catch (cause) {
      if (sequence === driftSequence && !controller.signal.aborted && snapshot.project === projectId && snapshot.id === reportId.trim()) error = message(cause);
    } finally {
      if (sequence === driftSequence) driftBusy = false;
    }
  }

  async function addCandidate() {
    if (!changeSummary.trim() || !rollbackPlan.trim() || !targetRevision.trim() || !baselineId || !candidateEvalId) return;
    const sequence = ++candidateSequence;
    candidateBusy = true; error = '';
    const snapshot = {
      project: projectId,
      baseline: baselineId,
      candidateEvaluation: candidateEvalId,
      candidateType,
      changeSummary: changeSummary.trim(),
      rollbackPlan: rollbackPlan.trim(),
      targetRevision: targetRevision.trim(),
      driftReportId: report?.baseline_eval_id === baselineId && report?.candidate_eval_id === candidateEvalId
        ? report.id : undefined,
    };
    try {
      const item = await createCandidate({
        projectId: snapshot.project,
        candidateType: snapshot.candidateType,
        changeSummary: snapshot.changeSummary,
        rollbackPlan: snapshot.rollbackPlan,
        targetRevision: snapshot.targetRevision,
        baselineEvalId: snapshot.baseline,
        candidateEvalId: snapshot.candidateEvaluation,
        driftReportId: snapshot.driftReportId,
      });
      if (sequence === candidateSequence && snapshot.project === projectId) {
        candidates = [item, ...candidates];
        const sameTarget = snapshot.baseline === baselineId
          && snapshot.candidateEvaluation === candidateEvalId
          && snapshot.candidateType === candidateType;
        if (sameTarget && changeSummary.trim() === snapshot.changeSummary) changeSummary = '';
        if (sameTarget && rollbackPlan.trim() === snapshot.rollbackPlan) rollbackPlan = '';
        if (sameTarget && targetRevision.trim() === snapshot.targetRevision) targetRevision = '';
      }
    } catch (cause) {
      if (sequence === candidateSequence && snapshot.project === projectId) error = message(cause);
    } finally {
      if (sequence === candidateSequence) candidateBusy = false;
    }
  }

  async function act(item: OptimizationCandidate, action: CandidateAction) {
    if (actionBusy[item.id]) return;
    const snapshot = {
      id: item.id,
      projectId: item.project_id,
      version: item.version,
      receipt: approvalReceipts[item.id],
      receiptDecided: approvalDecided[item.id] || false,
      reasonCode: reasonCodes[item.id]?.trim(),
    };
    actionBusy = { ...actionBusy, [item.id]: true }; error = '';
    try {
      if (action === 'approve') {
        if (!snapshot.receipt) throw new Error('Request approval before recording it');
        if (!snapshot.receiptDecided) {
          await decideCandidateApproval(snapshot.receipt.tool_call_id, snapshot.id, true);
          approvalDecided = { ...approvalDecided, [item.id]: true };
        }
      } else if (action === 'reject' && snapshot.receipt && !snapshot.receiptDecided) {
        await decideCandidateApproval(snapshot.receipt.tool_call_id, snapshot.id, false);
        approvalDecided = { ...approvalDecided, [item.id]: true };
      }
      const result = await transitionCandidate(snapshot.id, action, {
        projectId: snapshot.projectId,
        expectedVersion: snapshot.version,
        approvalId: snapshot.receipt?.approval_id,
        reasonCode: snapshot.reasonCode,
      });
      if (snapshot.projectId !== projectId) return;
      if ('tool_call_id' in result) {
        approvalReceipts = { ...approvalReceipts, [item.id]: result };
        approvalDecided = { ...approvalDecided, [item.id]: false };
      } else {
        candidates = candidates.map((current) =>
          current.id === snapshot.id && current.version === snapshot.version ? result : current
        );
      }
    } catch (cause) {
      const failure = message(cause);
      if (snapshot.projectId === projectId) {
        await loadCandidates(snapshot.projectId, false);
        if (snapshot.projectId === projectId) error = failure;
      }
    }
    finally { actionBusy = { ...actionBusy, [item.id]: false }; }
  }
</script>

<section class="review" aria-labelledby="drift-heading">
  <header><div><p class="eyebrow">Observed cohorts</p><h2 id="drift-heading"><TrendingUp size={18} /> Drift & revision review</h2></div></header>
  {#if error}<div class="error" role="alert">{error}</div>{/if}

  <div class="trend" aria-label="Evaluation trends">
    <h3>Recent quality trend</h3>
    {#if projectEvaluations.length === 0}<p class="empty">No evaluations for this project.</p>{:else}
      <div class="trend-list">{#each projectEvaluations.slice(0, 8) as item}<div><code>{item.id}</code><span>{display(item.aggregate_metrics.mean_score)}</span><meter min="0" max="1" value={item.aggregate_metrics.mean_score ?? 0}>{item.aggregate_metrics.mean_score ?? 0}</meter><small>{item.model_revision || 'model revision undeclared'} · {item.config_revision || 'config revision undeclared'}</small></div>{/each}</div>
    {/if}
  </div>

  <div class="controls">
    <label>Reference cohort<select aria-label="Drift reference cohort" bind:value={baselineId}>{#each projectEvaluations as item}<option value={item.id}>{item.id}</option>{/each}</select></label>
    <label>Comparison cohort<select aria-label="Drift comparison cohort" bind:value={candidateEvalId}>{#each projectEvaluations as item}<option value={item.id}>{item.id}</option>{/each}</select></label>
    <label>Minimum sample size<input type="number" min="2" max="10000" bind:value={minimumSampleSize} /></label>
    <button class="primary" onclick={compareDrift} disabled={driftBusy || !baselineId || !candidateEvalId || baselineId === candidateEvalId}>{#if driftBusy}<Loader size={15} class="spin" />{:else}<GitCompare size={15} />{/if} Create drift comparison</button>
  </div>
  <div class="open"><label>Existing report ID<input bind:value={reportId} placeholder="Report ID" /></label><button onclick={openReport} disabled={driftBusy || !reportId.trim()}>View report</button></div>

  {#if report}
    <article class="report" aria-label="Drift report">
      <header><h3>Drift report <code>{report.id}</code></h3><span>{report.warnings.length} warning{report.warnings.length === 1 ? '' : 's'}</span></header>
      {#if isInsufficientSample(report)}<div class="warning" role="status"><AlertTriangle size={17} /><strong>Insufficient sample.</strong> At least {report.minimum_sample_size} cases per cohort are required. Treat deltas as descriptive only.</div>
      {:else if report.warnings.length === 0}<div class="ok"><CheckCircle size={17} /> No configured drift thresholds were crossed.</div>{/if}
      <div class="identities"><div><h4>Baseline revision identity</h4>{#each Object.entries(report.baseline_identity) as [key, value]}<p><span>{label(key)}</span><code>{display(value)}</code></p>{/each}</div><div><h4>Candidate revision identity</h4>{#each Object.entries(report.candidate_identity) as [key, value]}<p><span>{label(key)}</span><code>{display(value)}</code></p>{/each}</div></div>
      {#if report.warnings.length}<ul class="warnings">{#each report.warnings as warning}<li><strong>{label(warning.metric)}</strong> — {label(warning.direction)} (delta {display(warning.delta)}, threshold {display(warning.threshold)})</li>{/each}</ul>{/if}
      <div class="deltas">{#each Object.entries(report.deltas) as [key, value]}<span><small>{label(key)}</small><b>{display(value)}</b></span>{/each}</div>
    </article>
  {/if}

  <section class="candidate-create" aria-labelledby="candidate-create-heading">
    <h3 id="candidate-create-heading">Propose optimization candidate</h3>
    <p>Recommendations are review records only. Nothing here changes the running model, prompt, policy, retrieval, or configuration.</p>
    <div class="candidate-form"><label>Type<select bind:value={candidateType}><option value="prompt">Prompt</option><option value="policy">Policy</option><option value="retrieval">Retrieval</option><option value="config">Config</option></select></label><label>Declared target revision<input bind:value={targetRevision} maxlength="255" /></label><label>Change summary<textarea bind:value={changeSummary} maxlength="1000"></textarea></label><label>Rollback plan<textarea bind:value={rollbackPlan} maxlength="2000"></textarea></label></div>
    <button class="primary" onclick={addCandidate} disabled={candidateBusy || !changeSummary.trim() || !rollbackPlan.trim() || !targetRevision.trim() || !baselineId || !candidateEvalId}>{candidateBusy ? 'Creating…' : 'Create candidate'}</button>
  </section>

  <section aria-labelledby="candidate-list-heading">
    <header><h3 id="candidate-list-heading">Optimization review queue</h3><button onclick={() => loadCandidates()} disabled={loadingCandidates}><span class:spin={loadingCandidates}><RefreshCw size={14} /></span> Refresh</button></header>
    {#if loadingCandidates && candidates.length === 0}<p class="empty">Loading candidates…</p>{:else if candidates.length === 0}<p class="empty">No optimization candidates for this project.</p>{/if}
    <div class="candidate-list">{#each candidates as item (item.id)}<article class="candidate"><header><div><span class="state">{label(item.state)}</span> <strong>{item.candidate_type}</strong></div><code>v{item.version} · {item.id}</code></header><p>{item.change_summary}</p><dl><div><dt>Declared revision</dt><dd>{item.target_revision}</dd></div><div><dt>Rollback</dt><dd>{item.rollback_plan}</dd></div></dl>
      {#if item.state === 'proposed'}<div class="actions"><button onclick={() => act(item, 'approval')} disabled={actionBusy[item.id] || Boolean(approvalReceipts[item.id])}>Request human approval</button>{#if approvalReceipts[item.id]}<p>Bound approval request <code>{approvalReceipts[item.id].approval_id}</code></p>{/if}<button onclick={() => act(item, 'approve')} disabled={actionBusy[item.id] || !approvalReceipts[item.id]}>Approve request and record decision</button><label>Rejection reason code<input maxlength="64" pattern="[a-z][a-z0-9_]*" value={reasonCodes[item.id] || ''} oninput={(event) => reasonCodes = { ...reasonCodes, [item.id]: event.currentTarget.value }} /></label><button onclick={() => act(item, 'reject')} disabled={actionBusy[item.id] || !validReason(reasonCodes[item.id])}>Reject</button></div>
      {:else if item.state === 'approved'}<div class="promotion"><label class="confirm"><input type="checkbox" checked={promotionConfirmed[item.id] || false} onchange={(event) => promotionConfirmed = { ...promotionConfirmed, [item.id]: event.currentTarget.checked }} /> I understand promotion only records declared revision <code>{item.target_revision}</code>; it does not mutate production or runtime configuration.</label><button class="danger" onclick={() => act(item, 'promote')} disabled={actionBusy[item.id] || !promotionConfirmed[item.id]}>Record promotion</button></div>
      {:else if item.state === 'promoted'}<div class="actions"><label>Rollback reason code<input maxlength="64" pattern="[a-z][a-z0-9_]*" value={reasonCodes[item.id] || ''} oninput={(event) => reasonCodes = { ...reasonCodes, [item.id]: event.currentTarget.value }} /></label><button onclick={() => act(item, 'rollback')} disabled={actionBusy[item.id] || !validReason(reasonCodes[item.id])}>Record rollback</button></div>{/if}
    </article>{/each}</div>
  </section>
</section>

<style>
  .review{background:var(--bg-secondary);border:1px solid var(--border);border-radius:.8rem;padding:1.2rem;display:grid;gap:1.2rem;min-width:0}.review>header,.report header,.candidate header,.review section>header{display:flex;justify-content:space-between;align-items:center;gap:.75rem}.eyebrow{margin:0;color:var(--accent);font-size:.66rem;text-transform:uppercase;letter-spacing:.12em;font-weight:750}h2,h3,h4,p{margin:.2rem 0}h2{font-size:1rem;display:flex;gap:.4rem;align-items:center}h3{font-size:.9rem}h4{font-size:.75rem}label{display:flex;flex-direction:column;gap:.35rem;font-size:.72rem;font-weight:650;color:var(--text-secondary)}select,input,textarea{width:100%;box-sizing:border-box;border:1px solid var(--border);border-radius:.45rem;background:var(--bg-tertiary);color:var(--text-primary);padding:.6rem;min-height:42px}textarea{min-height:75px;resize:vertical}button{display:inline-flex;align-items:center;justify-content:center;gap:.35rem;border:1px solid var(--border);border-radius:.45rem;background:var(--bg-tertiary);color:var(--text-primary);padding:.55rem .75rem;font-weight:700;cursor:pointer}button:disabled{opacity:.5;cursor:not-allowed}.primary{background:var(--accent);color:#07110f}.danger{border-color:var(--error);color:var(--error)}.controls{display:grid;grid-template-columns:1fr 1fr .65fr auto;gap:.7rem;align-items:end}.open{display:grid;grid-template-columns:1fr auto;gap:.7rem;align-items:end}.trend{border-bottom:1px solid var(--border);padding-bottom:1rem}.trend-list{display:grid;gap:.45rem;margin-top:.6rem}.trend-list>div{display:grid;grid-template-columns:minmax(7rem,1fr) 3rem minmax(5rem,2fr) minmax(10rem,2fr);gap:.6rem;align-items:center;font-size:.72rem}.trend-list code,.candidate code,.report code{overflow-wrap:anywhere}.trend-list meter{width:100%}.trend-list small,.empty,.candidate-create>p{color:var(--text-muted)}.report,.candidate-create,.candidate{border:1px solid var(--border);border-radius:.6rem;padding:1rem;background:var(--bg-primary)}.warning,.ok,.error{display:flex;align-items:center;gap:.4rem;padding:.65rem;border-radius:.45rem;margin:.7rem 0}.warning{background:color-mix(in srgb,var(--warning) 12%,transparent);color:var(--warning)}.ok{color:var(--success)}.error{background:color-mix(in srgb,var(--error) 12%,transparent);color:var(--error)}.identities{display:grid;grid-template-columns:1fr 1fr;gap:.7rem}.identities>div{border:1px solid var(--border);padding:.7rem;border-radius:.45rem;min-width:0}.identities p{display:flex;justify-content:space-between;gap:.5rem;font-size:.68rem}.warnings{font-size:.75rem}.deltas{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.5rem}.deltas span{display:flex;flex-direction:column;background:var(--bg-tertiary);padding:.5rem;border-radius:.4rem}.deltas small{color:var(--text-muted)}.candidate-form{display:grid;grid-template-columns:1fr 1fr;gap:.7rem;margin:.7rem 0}.candidate-list{display:grid;gap:.75rem;margin-top:.7rem}.state{font-size:.66rem;text-transform:uppercase;background:var(--bg-tertiary);padding:.2rem .4rem;border-radius:99px}.candidate p{font-size:.85rem}.candidate dl{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;font-size:.72rem}.candidate dt{color:var(--text-muted)}.candidate dd{margin:.2rem 0;overflow-wrap:anywhere}.actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.5rem;align-items:end}.promotion{display:grid;grid-template-columns:1fr auto;gap:.7rem;align-items:center}.confirm{flex-direction:row;align-items:flex-start}.confirm input{width:auto;min-height:auto;margin-top:.15rem}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  @media(max-width:750px){.controls,.open,.candidate-form,.identities,.candidate dl,.actions,.promotion{grid-template-columns:1fr}.trend-list>div{grid-template-columns:1fr 3rem}.trend-list meter,.trend-list small{grid-column:1/-1}.deltas{grid-template-columns:repeat(2,minmax(0,1fr))}.review{padding:1rem}.candidate header,.report header{align-items:flex-start;flex-direction:column}.candidate header code{max-width:100%}}
</style>
