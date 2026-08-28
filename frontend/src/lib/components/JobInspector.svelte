<script lang="ts">
  import { AlertTriangle, Ban, BriefcaseBusiness, Loader2, RefreshCw, RotateCcw } from 'lucide-svelte';
  import { cancelJob, getJob, listJobs, retryJob, type DurableJob, type JobStatus } from '$lib/jobs';

  let jobs: DurableJob[] = $state([]);
  let selected: DurableJob | null = $state(null);
  let projectId = $state('');
  let projectFilter = $state('');
  let loading = $state(true);
  let detailLoading = $state(false);
  let busy = $state('');
  let error = $state('');
  let requestVersion = 0;

  const labels: Record<JobStatus, string> = {
    pending: 'Pending', running: 'Running', succeeded: 'Succeeded', failed: 'Failed',
    dead_letter: 'Dead letter', cancelled: 'Cancelled',
  };
  const terminal = (status: JobStatus) => ['succeeded', 'failed', 'dead_letter', 'cancelled'].includes(status);
  const date = (value: string | null) => value ? new Date(value).toLocaleString() : '—';
  const short = (value: string) => value.length > 24 ? `${value.slice(0, 14)}…${value.slice(-7)}` : value;
  const safeCode = (value: string | null) => value ? value.replaceAll('_', ' ') : 'No error recorded';

  function resultMetadata(result: Record<string, unknown> | null): [string, string][] {
    if (!result) return [];
    const allowed = ['export_id', 'run_id', 'schema_version', 'content_checksum', 'manifest_checksum', 'created_at'];
    return allowed.flatMap((key) => {
      const value = result[key];
      return typeof value === 'string' || typeof value === 'number' ? [[key.replaceAll('_', ' '), String(value)] as [string, string]] : [];
    });
  }

  async function load(options: { quiet?: boolean } = {}) {
    const version = ++requestVersion;
    if (!options.quiet) loading = true;
    error = '';
    try {
      const loaded = await listJobs({ projectId: projectFilter || undefined, limit: 50 });
      if (version !== requestVersion) return;
      jobs = loaded;
      if (selected) selected = loaded.find((job) => job.job_id === selected?.job_id) ?? null;
    } catch (cause) {
      if (version === requestVersion) error = cause instanceof Error ? cause.message : 'Jobs unavailable';
    } finally {
      if (version === requestVersion) loading = false;
    }
  }

  function applyFilter(event: SubmitEvent) {
    event.preventDefault();
    projectFilter = projectId.trim();
    selected = null;
    void load();
  }

  async function inspect(job: DurableJob) {
    selected = job;
    detailLoading = true;
    error = '';
    try { selected = await getJob(job.job_id, job.project_id); }
    catch (cause) { error = cause instanceof Error ? cause.message : 'Job detail unavailable'; }
    finally { detailLoading = false; }
  }

  async function act(action: 'cancel' | 'retry') {
    if (!selected) return;
    busy = action;
    error = '';
    try {
      if (action === 'cancel') await cancelJob(selected.job_id, selected.project_id);
      else await retryJob(selected.job_id, selected.project_id);
      selected = await getJob(selected.job_id, selected.project_id);
      await load({ quiet: true });
    } catch (cause) { error = cause instanceof Error ? cause.message : `Could not ${action} job`; }
    finally { busy = ''; }
  }

  $effect(() => {
    void load();
    const timer = setInterval(() => void load({ quiet: true }), 8000);
    return () => clearInterval(timer);
  });
</script>

<section class="jobs-card" aria-labelledby="jobs-heading">
  <header class="jobs-header">
    <div><p class="eyebrow">Restart-safe work</p><h2 id="jobs-heading"><BriefcaseBusiness size={17} /> Durable jobs</h2></div>
    <button class="icon-button" onclick={() => load()} disabled={loading} aria-label="Refresh durable jobs"><RefreshCw size={15} class={loading ? 'spin' : ''} /> Refresh</button>
  </header>

  <form class="filters" onsubmit={applyFilter}>
    <label for="job-project">Project scope</label>
    <input id="job-project" bind:value={projectId} maxlength="255" placeholder="All owned projects" />
    <button type="submit" disabled={loading}>Apply filter</button>
  </form>

  {#if error}<p class="error" role="alert"><AlertTriangle size={15} /> {error}</p>{/if}
  {#if loading}
    <div class="state" aria-live="polite"><Loader2 size={20} class="spin" /> Loading durable jobs…</div>
  {:else if jobs.length === 0}
    <div class="state"><BriefcaseBusiness size={22} /><strong>No durable jobs found</strong><span>{projectFilter ? `No jobs in project “${projectFilter}”.` : 'Submitted background work will appear here.'}</span></div>
  {:else}
    <div class="workspace">
      <div class="job-list" aria-label="Durable job history">
        {#each jobs as job}
          <button class="job-row" class:selected={selected?.job_id === job.job_id} onclick={() => inspect(job)} aria-label={`Inspect ${job.kind} job ${job.job_id}`}>
            <span class="row-top"><strong>{job.kind.replaceAll('_', ' ')}</strong><span class="status status-{job.status}">{labels[job.status]}</span></span>
            <span class="row-meta"><code title={job.job_id}>{short(job.job_id)}</code><span>{job.project_id}</span></span>
            <span class="row-bottom"><span>Attempt {job.attempts} of {job.max_attempts}</span><time>{date(job.updated_at)}</time></span>
          </button>
        {/each}
      </div>

      <div class="detail" aria-live="polite">
        {#if !selected}
          <div class="state compact"><strong>Select a job</strong><span>Inspect lifecycle, attempts, lineage, and safe result metadata.</span></div>
        {:else if detailLoading}
          <div class="state compact"><Loader2 size={18} class="spin" /> Loading job detail…</div>
        {:else}
          <div class="detail-heading">
            <div><p class="eyebrow">Job inspector</p><h3>{selected.kind.replaceAll('_', ' ')}</h3></div>
            <span class="status status-{selected.status}">{labels[selected.status]}</span>
          </div>
          <dl class="facts">
            <div><dt>Job ID</dt><dd><code title={selected.job_id}>{selected.job_id}</code></dd></div>
            <div><dt>Project</dt><dd>{selected.project_id}</dd></div>
            <div><dt>Attempts</dt><dd>{selected.attempts} / {selected.max_attempts}</dd></div>
            <div><dt>Created</dt><dd>{date(selected.created_at)}</dd></div>
            <div><dt>Updated</dt><dd>{date(selected.updated_at)}</dd></div>
            <div><dt>Completed</dt><dd>{date(selected.completed_at)}</dd></div>
            <div class="wide"><dt>Idempotency lineage</dt><dd><code>{selected.idempotency_key || 'Not supplied'}</code></dd></div>
          </dl>

          {#if selected.error_code}
            <div class="notice failure"><strong>Safe failure code</strong><span>{safeCode(selected.error_code)}</span></div>
          {/if}
          {#if selected.result}
            {@const metadata = resultMetadata(selected.result)}
            <div class="result">
              <strong>Result metadata</strong>
              {#if metadata.length}
                <dl>{#each metadata as [key, value]}<div><dt>{key}</dt><dd title={value}>{short(value)}</dd></div>{/each}</dl>
              {:else}<p>Result stored securely. Payload content is not shown.</p>{/if}
            </div>
          {/if}

          <div class="actions">
            {#if selected.status === 'pending' || selected.status === 'running'}
              <button class="danger" onclick={() => act('cancel')} disabled={Boolean(busy)}>{#if busy === 'cancel'}<Loader2 size={15} class="spin" /> Cancelling…{:else}<Ban size={15} /> Cancel job{/if}</button>
            {:else if selected.status === 'failed' || selected.status === 'dead_letter'}
              <button class="primary" onclick={() => act('retry')} disabled={Boolean(busy)}>{#if busy === 'retry'}<Loader2 size={15} class="spin" /> Retrying…{:else}<RotateCcw size={15} /> Retry job{/if}</button>
            {:else if terminal(selected.status)}<span class="terminal-note">No actions available for this terminal state.</span>{/if}
          </div>
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .jobs-card{display:grid;gap:16px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:.75rem;padding:1.25rem;min-width:0}.jobs-header,.detail-heading,.row-top,.row-meta,.row-bottom{display:flex;align-items:center;justify-content:space-between;gap:10px}.eyebrow{margin:0;color:var(--text-muted);font-size:10px;text-transform:uppercase;letter-spacing:.09em}.jobs-header h2,.detail-heading h3{display:flex;align-items:center;gap:7px;margin:2px 0 0;font-size:.9375rem}.filters{display:grid;grid-template-columns:auto minmax(160px,320px) auto;align-items:center;gap:8px}.filters label{font-size:12px;color:var(--text-muted)}button,input{min-height:40px;border:1px solid var(--border);border-radius:7px;background:var(--bg-tertiary);color:var(--text-primary);padding:7px 10px}button{display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer}button:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}button:disabled{opacity:.55;cursor:not-allowed}.icon-button{font-size:12px}.workspace{display:grid;grid-template-columns:minmax(260px,.85fr) minmax(340px,1.15fr);gap:12px;min-width:0}.job-list{display:grid;gap:7px;align-content:start;max-height:540px;overflow:auto}.job-row{display:grid;gap:8px;width:100%;text-align:left;padding:11px;background:var(--bg-tertiary)}.job-row.selected{border-color:var(--accent);box-shadow:inset 3px 0 var(--accent)}.row-top strong{font-size:13px;text-transform:capitalize}.row-meta,.row-bottom{color:var(--text-muted);font-size:11px}.row-meta code{overflow:hidden;text-overflow:ellipsis}.detail{min-width:0;border:1px solid var(--border);border-radius:9px;padding:14px;background:var(--bg-tertiary)}.facts{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0}.facts div{min-width:0}.facts .wide{grid-column:1/-1}.facts dt,.result dt{color:var(--text-muted);font-size:10px;text-transform:uppercase;letter-spacing:.05em}.facts dd,.result dd{margin:3px 0 0;font-size:12px;overflow-wrap:anywhere}.status{padding:3px 7px;border-radius:999px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;background:rgba(139,148,158,.15);color:var(--text-muted)}.status-running,.status-pending{color:var(--warning);background:rgba(210,153,34,.13)}.status-succeeded{color:var(--success);background:rgba(63,185,80,.13)}.status-failed,.status-dead_letter{color:var(--error);background:rgba(248,81,73,.13)}.notice,.result{display:grid;gap:6px;margin-top:10px;border:1px solid var(--border);border-radius:8px;padding:10px;font-size:12px}.notice.failure{border-color:rgba(248,81,73,.3)}.notice span,.result p{margin:0;color:var(--text-muted)}.result dl{display:grid;gap:5px;margin:0}.result dl div{display:flex;justify-content:space-between;gap:12px}.actions{display:flex;justify-content:flex-end;margin-top:14px}.danger{color:var(--error)}.primary{background:var(--accent);color:#071713;border-color:transparent;font-weight:700}.terminal-note{color:var(--text-muted);font-size:11px}.state{display:flex;min-height:140px;flex-direction:column;align-items:center;justify-content:center;gap:7px;text-align:center;color:var(--text-muted);font-size:12px}.state.compact{min-height:220px}.error{display:flex;align-items:center;gap:7px;margin:0;color:var(--error);font-size:12px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  @media(max-width:760px){.jobs-header{align-items:stretch;flex-direction:column}.jobs-header .icon-button{width:100%}.filters{grid-template-columns:1fr}.workspace{grid-template-columns:1fr}.job-list{max-height:320px}.facts{grid-template-columns:1fr}.facts .wide{grid-column:auto}.actions button{width:100%}}
</style>
