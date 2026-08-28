<script lang="ts">
  import { Ban, Copy, Download, FileArchive, Loader2, Share2, ShieldCheck } from 'lucide-svelte';
  import {
    createRunExport,
    createShareGrant,
    downloadRunExport,
    listRunExports,
    listShareGrants,
    revokeShareGrant,
    type RunExport,
    type ShareGrant,
  } from '$lib/runs';

  let { runId }: { runId: string } = $props();
  let exports: RunExport[] = $state([]);
  let selectedExportId = $state('');
  let grants: ShareGrant[] = $state([]);
  let recipientUserId = $state('');
  let purpose: 'audit' | 'incident_review' | 'evaluation' | 'support' = $state('audit');
  let expiryHours = $state(1);
  let oneTimeToken = $state('');
  let loading = $state(false);
  let action = $state('');
  let error = $state('');
  let requestVersion = 0;

  const short = (value: string) => value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-5)}` : value;
  const date = (value: string) => new Date(value).toLocaleString();

  async function load(targetRunId: string) {
    const version = ++requestVersion;
    loading = true;
    error = '';
    oneTimeToken = '';
    try {
      const loaded = await listRunExports(targetRunId);
      if (version !== requestVersion) return;
      exports = loaded;
      if (!loaded.some((item) => item.export_id === selectedExportId)) {
        selectedExportId = loaded[0]?.export_id ?? '';
      }
      grants = selectedExportId ? await listShareGrants(targetRunId, selectedExportId) : [];
    } catch (cause) {
      if (version === requestVersion) error = cause instanceof Error ? cause.message : 'Exports unavailable';
    } finally {
      if (version === requestVersion) loading = false;
    }
  }

  async function loadGrants() {
    oneTimeToken = '';
    grants = selectedExportId ? await listShareGrants(runId, selectedExportId) : [];
  }

  async function createExport() {
    action = 'export'; error = '';
    try {
      const created = await createRunExport(runId);
      await load(runId);
      selectedExportId = created.export_id;
      await loadGrants();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Export failed';
    } finally { action = ''; }
  }

  async function downloadExport() {
    if (!selectedExportId) return;
    action = 'download'; error = '';
    try {
      const bundle = await downloadRunExport(runId, selectedExportId);
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `archon-run-${runId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Download failed';
    } finally { action = ''; }
  }

  async function createGrant() {
    if (!selectedExportId || !recipientUserId.trim()) return;
    action = 'share'; error = ''; oneTimeToken = '';
    try {
      const created = await createShareGrant(
        runId, selectedExportId, recipientUserId.trim(), purpose, expiryHours * 3600,
      );
      oneTimeToken = created.token;
      recipientUserId = '';
      grants = await listShareGrants(runId, selectedExportId);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Share grant failed';
    } finally { action = ''; }
  }

  async function revoke(grantId: string) {
    action = grantId; error = '';
    try {
      await revokeShareGrant(grantId);
      await loadGrants();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Revocation failed';
    } finally { action = ''; }
  }

  async function copyToken() {
    if (oneTimeToken) await navigator.clipboard.writeText(oneTimeToken);
  }

  $effect(() => {
    const selectedRun = runId;
    queueMicrotask(() => void load(selectedRun));
  });
</script>

<section class="export-panel" aria-labelledby="export-heading">
  <header>
    <div><small>Evidence disclosure</small><h3 id="export-heading"><ShieldCheck size={17} /> Secure export & sharing</h3></div>
    <button class="primary" onclick={createExport} disabled={Boolean(action)}>
      {#if action === 'export'}<Loader2 size={15} class="spin" />{:else}<FileArchive size={15} />{/if}
      Create export
    </button>
  </header>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if loading}<p class="muted" aria-live="polite">Loading disclosure records…</p>
  {:else if exports.length === 0}<p class="empty">No disclosure-scanned exports for this run.</p>
  {:else}
    <div class="export-row">
      <label>Export
        <select bind:value={selectedExportId} onchange={loadGrants}>
          {#each exports as item}<option value={item.export_id}>{date(item.created_at)} · {short(item.content_checksum)}</option>{/each}
        </select>
      </label>
      <button onclick={downloadExport} disabled={Boolean(action)}><Download size={15} /> Download JSON</button>
    </div>

    <div class="share-form">
      <label>Recipient user ID<input bind:value={recipientUserId} maxlength="255" autocomplete="off" placeholder="Authenticated recipient ID" /></label>
      <label>Purpose<select bind:value={purpose}><option value="audit">Audit</option><option value="incident_review">Incident review</option><option value="evaluation">Evaluation</option><option value="support">Support</option></select></label>
      <label>Expires in<select bind:value={expiryHours}><option value={1}>1 hour</option><option value={24}>24 hours</option><option value={168}>7 days</option></select></label>
      <button class="primary" onclick={createGrant} disabled={Boolean(action) || !recipientUserId.trim()}><Share2 size={15} /> Create read-only grant</button>
    </div>

    {#if oneTimeToken}
      <div class="token" role="status">
        <strong>Copy this token now</strong><span>It is never stored or shown again.</span>
        <code>{oneTimeToken}</code>
        <button onclick={copyToken}><Copy size={14} /> Copy token</button>
      </div>
    {/if}

    <div class="grant-list">
      {#each grants as grant}
        <article class:revoked={Boolean(grant.revoked_at)}>
          <div><strong>{grant.purpose.replaceAll('_', ' ')}</strong><span>{short(grant.recipient_user_id)} · expires {date(grant.expires_at)}</span></div>
          {#if grant.revoked_at}<span class="status">Revoked</span>{:else}<button class="danger" onclick={() => revoke(grant.grant_id)} disabled={Boolean(action)}><Ban size={14} /> Revoke</button>{/if}
        </article>
      {/each}
      {#if grants.length === 0}<p class="muted">No active or historical grants.</p>{/if}
    </div>
  {/if}
</section>

<style>
  .export-panel{display:grid;gap:12px;border:1px solid var(--border);border-radius:10px;padding:12px;background:var(--surface)}
  header,.export-row,article{display:flex;align-items:center;justify-content:space-between;gap:10px}header small{color:var(--muted);text-transform:uppercase;letter-spacing:.08em}h3{display:flex;align-items:center;gap:7px;margin:2px 0 0;font-size:14px}button,select,input{min-height:44px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--text);padding:8px}button{display:inline-flex;align-items:center;justify-content:center;gap:6px;cursor:pointer}button:disabled{opacity:.55;cursor:not-allowed}.primary{background:var(--accent);color:#071713;border-color:transparent;font-weight:700}.danger{color:var(--error)}label{display:grid;gap:4px;color:var(--muted);font-size:11px}.export-row label{flex:1}.share-form{display:grid;grid-template-columns:minmax(180px,1fr) minmax(130px,.55fr) minmax(100px,.4fr) auto;gap:8px;align-items:end}.token{display:grid;grid-template-columns:1fr auto;gap:5px 10px;border:1px solid rgba(85,214,190,.35);border-radius:8px;padding:10px;background:rgba(85,214,190,.07)}.token span,.muted,.empty{color:var(--muted);font-size:12px}.token code{grid-column:1/-1;overflow-wrap:anywhere}.grant-list{display:grid;gap:6px}article{border-top:1px solid var(--border);padding-top:8px}article div{display:grid;gap:2px}article span{font-size:11px;color:var(--muted)}article.revoked{opacity:.65}.status{font-weight:700}.error{color:var(--error);font-size:12px}:global(.spin){animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
  @media(max-width:760px){header,.export-row{align-items:stretch;flex-direction:column}.share-form{grid-template-columns:1fr}.primary,button{width:100%}.token{grid-template-columns:1fr}}
</style>
