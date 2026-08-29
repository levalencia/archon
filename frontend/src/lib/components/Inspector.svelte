<script lang="ts">
  import type { Artifact, ContextStats, InspectorTab, LogEntry, RunStats, Message } from '$lib/types';
  import { getRunContext, listRuns, type ContextManifest } from '$lib/runs';
  import RunTimeline from '$lib/components/RunTimeline.svelte';
  import { CheckCircle2, AlertTriangle, FileOutput, ExternalLink } from 'lucide-svelte';
  let { stats, conversationId = '', artifacts = [], context, logs = [], message, active = 'run', onTab = (_t: InspectorTab) => {}, onOpenArtifact = () => {}, onClearLogs = () => {}, onFork = (_id: string) => {} }: { stats: RunStats; conversationId?: string; artifacts?: Artifact[]; context?: ContextStats; logs?: LogEntry[]; message?: Message; active?: InspectorTab; onTab?: (tab: InspectorTab) => void; onOpenArtifact?: () => void; onClearLogs?: () => void; onFork?: (id: string) => void } = $props();
  const tabs: InspectorTab[] = ['run','evidence','context','logs'];
  let verifierOk = $derived(message?.verifier?.supported !== false && !message?.verifier?.unsupported_claims?.length);
  let contextManifest: ContextManifest | null = $state(null);
  let contextManifestError = $state('');
  let contextManifestLoading = $state(false);
  let contextRequest = 0;

  async function loadContextManifest(id: string) {
    const request = ++contextRequest;
    contextManifestLoading = true;
    contextManifestError = '';
    contextManifest = null;
    try {
      const runs = await listRuns({ conversationId: id, limit: 1 });
      if (request !== contextRequest) return;
      if (!runs.length) {
        contextManifestError = 'No persisted run context yet.';
        return;
      }
      contextManifest = await getRunContext(runs[0].run_id);
    } catch (cause) {
      if (request === contextRequest) {
        contextManifestError = cause instanceof Error ? cause.message : 'Context provenance unavailable';
      }
    } finally {
      if (request === contextRequest) contextManifestLoading = false;
    }
  }

  $effect(() => {
    const selectedTab = active;
    const selectedConversation = conversationId;
    if (selectedTab === 'context' && selectedConversation) {
      queueMicrotask(() => void loadContextManifest(selectedConversation));
    }
  });
</script>
<div class="inspector">
  <header><div><p class="eyebrow">Inspector</p><h2>Run evidence</h2></div><span class="live"><i></i> Live</span></header>
  <div class="tabs" role="tablist" aria-label="Inspector views">{#each tabs as tab}<button role="tab" aria-selected={active === tab} onclick={() => onTab(tab)}>{tab[0].toUpperCase()+tab.slice(1)}</button>{/each}</div>
  <div class="inspector-content">
  {#if active === 'run'}
    <RunTimeline {conversationId} {onFork} />
    <hr class="my-4 border-[var(--border)]" />
    <p class="section-label">Current run</p><div class="stat-grid"><div><span>Latency</span><strong>{stats.latency}</strong></div><div><span>Tokens</span><strong>{stats.tokens}</strong></div><div><span>Tools</span><strong>{stats.tools}</strong></div><div><span>Iterations</span><strong>{stats.iterations}</strong></div>{#if stats.cost}<div><span>Cost</span><strong class="text-[var(--accent)]">{stats.cost}</strong></div>{/if}</div>
  {:else if active === 'evidence'}
    <div class="mb-4 flex items-start gap-3 rounded-xl border p-3 {verifierOk ? 'border-[rgba(85,214,190,.35)] bg-[rgba(85,214,190,.07)]' : 'border-[rgba(240,189,98,.4)] bg-[rgba(240,189,98,.08)]'}">
      {#if verifierOk}<CheckCircle2 class="mt-0.5 shrink-0 text-[var(--accent)]" size={18}/><div><strong class="text-sm">Verification passed</strong><p class="mt-1 text-xs text-[var(--muted)]">No unsupported claims reported.</p></div>{:else}<AlertTriangle class="mt-0.5 shrink-0 text-[var(--warning)]" size={18}/><div><strong class="text-sm">Verification needs review</strong><p class="mt-1 text-xs text-[var(--muted)]">{message?.verifier?.reason || `${message?.verifier?.unsupported_claims?.length || 0} unsupported claims`}</p></div>{/if}
    </div>
    <p class="section-label">Sources</p>
    {#if message?.sources?.length}<div class="space-y-2">{#each message.sources as source, i}<article class="rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3"><div class="flex items-start gap-2"><span class="rounded bg-[rgba(85,214,190,.12)] px-1.5 py-1 font-mono text-[10px] font-bold text-[var(--accent)]">{source.id || `S${i + 1}`}</span><div class="min-w-0 flex-1"><strong class="block truncate text-xs">{source.title || 'Untitled source'}</strong>{#if source.url}<a href={source.url} target="_blank" rel="noopener" class="mt-1 flex items-center gap-1 truncate text-[11px] text-[var(--muted)]">{source.url}<ExternalLink size={11}/></a>{/if}</div>{#if source.score != null}<span class="font-mono text-[11px] text-[var(--accent)]">{(source.score * 100).toFixed(0)}%</span>{/if}</div></article>{/each}</div>{:else}<div class="empty-detail">Source IDs, titles, and relevance scores will appear here.</div>{/if}
    <p class="section-label mt-4">Artifacts</p>{#if artifacts.length}<button class="artifact-card" onclick={onOpenArtifact}><span class="flex items-center gap-2"><FileOutput size={15}/><strong>{artifacts[0].title}</strong></span><span>{artifacts.length} available · Open preview</span></button>{:else}<div class="empty-detail">No generated artifacts for this run.</div>{/if}
    {#if message?.evalScores?.length}<p class="section-label mt-4">Evaluations</p><div class="space-y-2">{#each message.evalScores as score}<div class="rounded-lg border border-[var(--border)] p-3 text-xs"><div class="flex justify-between"><strong>{score.name}</strong><span class="font-mono text-[var(--accent)]">{Math.round(score.score * 100)}%</span></div><p class="mb-0 text-[var(--muted)]">{score.reason}</p></div>{/each}</div>{/if}
  {:else if active === 'context'}
    <p class="section-label">Context window</p><div class="context-meter"><div><span>Utilization</span><strong>{context?.utilization_pct || 0}%</strong></div><progress max="100" value={context?.utilization_pct || 0}></progress><small>{context?.tokens?.toLocaleString() || 0} of {context?.budget?.toLocaleString() || 0} tokens</small></div>
    {#if context?.compacted}<div class="mt-3 rounded-lg border border-[rgba(85,214,190,.25)] bg-[rgba(85,214,190,.08)] p-3 text-xs text-[var(--accent)]">Context compacted — {context.tokens_before?.toLocaleString()} → {context.tokens_after?.toLocaleString()} tokens ({context.saved_pct}% saved)</div>{/if}
    <p class="section-label mt-4">Effective context</p>
    {#if contextManifestLoading}
      <div class="empty-detail" aria-live="polite">Loading persisted provenance…</div>
    {:else if contextManifestError}
      <div class="empty-detail" role="status">{contextManifestError}</div>
    {:else if contextManifest}
      <div class="space-y-3 rounded-xl border border-[var(--border)] bg-[var(--panel-2)] p-3 text-xs">
        <div class="stat-grid">
          <div><span>Selected</span><strong>{contextManifest.selected_message_ids.length}</strong></div>
          <div><span>Summarized</span><strong>{contextManifest.summarized_message_ids.length}</strong></div>
          <div><span>Memories</span><strong>{contextManifest.memory_ids.length}</strong></div>
          <div><span>Skills</span><strong>{contextManifest.skill_ids.length}</strong></div>
          <div><span>Assets</span><strong>{contextManifest.input_asset_fingerprints.length}</strong></div>
          <div><span>Estimate</span><strong>{contextManifest.estimated_tokens.toLocaleString()}</strong></div>
        </div>
        <dl class="space-y-2 text-[11px] text-[var(--muted)]">
          <div class="flex justify-between gap-3"><dt>Run</dt><dd class="truncate font-mono text-[var(--text)]" title={contextManifest.run_id}>{contextManifest.run_id}</dd></div>
          <div class="flex justify-between gap-3"><dt>Compaction</dt><dd class="text-right text-[var(--text)]">{contextManifest.summary_version || 'none'}{contextManifest.truncation_reason ? ` · ${contextManifest.truncation_reason}` : ''}</dd></div>
          <div class="flex justify-between gap-3"><dt>Manifest</dt><dd class="font-mono text-[var(--text)]" title={contextManifest.manifest_hash}>{contextManifest.manifest_hash.slice(0, 12)}…</dd></div>
        </dl>
      </div>
    {:else}
      <div class="empty-detail">Select a persisted conversation to inspect its latest context.</div>
    {/if}
  {:else}
    <div class="log-toolbar"><span>{logs.length} events</span><button onclick={onClearLogs}>Clear</button><button onclick={() => navigator.clipboard?.writeText(logs.map(l => `${l.ts || ''} [${l.level || ''}] ${l.event || ''}`).join('\n'))}>Copy</button></div><div class="log-list">{#if logs.length === 0}<div class="empty-detail">Waiting for backend events…</div>{/if}{#each logs as log}<div><time>{log.ts}</time><strong class:error-text={log.level === 'error'}>{log.level}</strong><span>{log.event}</span></div>{/each}</div>
  {/if}
  </div>
</div>
