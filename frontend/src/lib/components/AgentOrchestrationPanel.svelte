<script lang="ts">
  import { getRunEvents, listRunChildren } from '$lib/runs';
  import type { ChildAgentStatus, Message, OrchestrationStatus } from '$lib/types';

  let { message, runId = '', loading = false, error = '' }: { message?: Message; runId?: string; loading?: boolean; error?: string } = $props();
  let persistedOrchestration = $state<OrchestrationStatus | undefined>();
  let persistedChildren = $state<ChildAgentStatus[]>([]);
  let persistedError = $state('');
  let persistedLoading = $state(false);
  let requestVersion = 0;
  let orchestration = $derived(message?.orchestration || persistedOrchestration);
  let children = $derived(message?.child_agents?.length ? message.child_agents : persistedChildren);

  function label(value: string | undefined): string {
    return (value || 'unknown').replaceAll('_', ' ');
  }

  function failed(status: string): boolean {
    return ['failed', 'timed_out', 'cancelled', 'denied'].includes(status);
  }

  async function loadPersistedEvidence(id: string) {
    const request = ++requestVersion;
    persistedLoading = true;
    persistedError = '';
    persistedOrchestration = undefined;
    persistedChildren = [];
    try {
      const [runs, events] = await Promise.all([listRunChildren(id), getRunEvents(id)]);
      if (request !== requestVersion) return;
      const routed = events.find((event) => event.kind === 'orchestration_routed')?.payload;
      if (routed?.requested_mode && routed?.resolved_mode && routed?.reason_code) {
        persistedOrchestration = routed as unknown as OrchestrationStatus;
      }
      const byChild = new Map<string, ChildAgentStatus>();
      for (const event of events.filter((item) => item.kind.startsWith('delegation_'))) {
        const child = event.payload as unknown as ChildAgentStatus;
        if (child.child_id) byChild.set(child.child_id, { ...byChild.get(child.child_id), ...child });
      }
      for (const run of runs) {
        const prior = byChild.get(run.run_id);
        byChild.set(run.run_id, {
          child_id: run.run_id,
          parent_run_id: run.parent_run_id || id,
          profile_id: prior?.profile_id || 'bounded-child',
          specialist_kind: prior?.specialist_kind || 'dynamic',
          status: (prior?.status || run.status) as ChildAgentStatus['status'],
          reason_code: prior?.reason_code || run.stop_reason,
          input_tokens: prior?.input_tokens ?? run.input_tokens,
          output_tokens: prior?.output_tokens ?? run.output_tokens,
          total_tokens: prior?.total_tokens ?? run.total_tokens,
          iterations: prior?.iterations ?? run.iterations,
          tool_count: prior?.tool_count,
        });
      }
      persistedChildren = [...byChild.values()];
    } catch (cause) {
      if (request === requestVersion) {
        persistedError = cause instanceof Error ? cause.message : 'Agent evidence unavailable';
      }
    } finally {
      if (request === requestVersion) persistedLoading = false;
    }
  }

  $effect(() => {
    const selectedRun = runId;
    const hasLiveEvidence = Boolean(message?.orchestration || message?.child_agents?.length);
    if (selectedRun && !hasLiveEvidence) {
      queueMicrotask(() => void loadPersistedEvidence(selectedRun));
    }
  });
</script>

<section class="agent-panel" aria-label="Agent orchestration evidence" aria-live="polite">
  {#if orchestration}
    <div class="route-card">
      <div>
        <span class="eyebrow">Routing decision</span>
        <strong>{label(orchestration.requested_mode)} → {label(orchestration.resolved_mode)}</strong>
      </div>
      <span class:degraded={orchestration.degraded} class="route-state">
        {orchestration.degraded ? 'Degraded' : 'Bounded'}
      </span>
      <small>{label(orchestration.reason_code)}</small>
    </div>

    {#if children.length}
      <div class="agent-tree">
        <div class="parent-node">
          <span>Parent</span>
          <strong>Coordinator runtime</strong>
        </div>
        <ol aria-label="Delegated child agents">
          {#each children as child}
            <li>
              <span class="connector" aria-hidden="true"></span>
              <article>
                <div class="agent-heading">
                  <strong>{label(child.profile_id)}</strong>
                  <span class:failed={failed(child.status)} class="status">{label(child.status)}</span>
                </div>
                <p>{label(child.specialist_kind)} specialist</p>
                <dl>
                  <div><dt>Tokens</dt><dd>{child.total_tokens ?? '—'}</dd></div>
                  <div><dt>Tools</dt><dd>{child.tool_count ?? '—'}</dd></div>
                  <div><dt>Iterations</dt><dd>{child.iterations ?? '—'}</dd></div>
                </dl>
                {#if child.reason_code}<small>{label(child.reason_code)}</small>{/if}
              </article>
            </li>
          {/each}
        </ol>
      </div>
    {:else}
      <div class="empty-detail">This run stayed on the single-agent path.</div>
    {/if}
  {:else if loading || persistedLoading}
    <div class="empty-detail">Loading persisted agent evidence…</div>
  {:else if error || persistedError}
    <div class="empty-detail" role="status">{error || persistedError}</div>
  {:else}
    <div class="empty-detail">No orchestration evidence is available for this run.</div>
  {/if}
</section>

<style>
  .agent-panel { display: grid; gap: .9rem; }
  .route-card, article, .parent-node { border: 1px solid var(--border); border-radius: 10px; background: var(--panel-2); padding: .75rem; }
  .route-card { display: grid; grid-template-columns: 1fr auto; gap: .35rem .75rem; }
  .route-card div { display: grid; gap: .2rem; }
  .route-card small { grid-column: 1 / -1; color: var(--muted); text-transform: capitalize; }
  .eyebrow { color: var(--muted); font-size: .65rem; letter-spacing: .08em; text-transform: uppercase; }
  .route-state, .status { align-self: start; border-radius: 999px; background: color-mix(in srgb, var(--cogentrex-green) 15%, transparent); color: var(--cogentrex-green); padding: .2rem .45rem; font-size: .65rem; font-weight: 700; text-transform: capitalize; }
  .route-state.degraded, .status.failed { background: color-mix(in srgb, var(--cogentrex-coral) 14%, transparent); color: var(--cogentrex-coral); }
  .agent-tree { display: grid; gap: .4rem; }
  .parent-node { border-color: var(--accent); display: grid; gap: .15rem; }
  .parent-node span { color: var(--accent); font-size: .65rem; text-transform: uppercase; }
  ol { list-style: none; margin: 0 0 0 1rem; padding: .35rem 0 0 1rem; border-left: 1px solid var(--accent); display: grid; gap: .55rem; }
  li { position: relative; }
  .connector { position: absolute; left: -1rem; top: 1.1rem; width: 1rem; border-top: 1px solid var(--accent); }
  article { display: grid; gap: .35rem; }
  .agent-heading { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
  article p, article small { margin: 0; color: var(--muted); font-size: .7rem; text-transform: capitalize; }
  dl { display: flex; gap: .75rem; margin: 0; }
  dl div { display: flex; gap: .25rem; font-size: .68rem; }
  dt { color: var(--muted); }
  dd { margin: 0; font-family: ui-monospace, monospace; }
</style>
