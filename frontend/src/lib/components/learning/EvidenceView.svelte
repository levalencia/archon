<script lang="ts">
  import { Check, ExternalLink, Minus, Search } from 'lucide-svelte';
  import { STATUS_META, evidenceFilter, type ConceptStatus, type VisualLearningStudio } from '$lib/visual-learning';

  let { studio }: { studio: VisualLearningStudio } = $props();
  let query = $state('');
  let status = $state<ConceptStatus | 'all'>('all');
  let selectedId = $state('agent-anatomy');
  let rows = $derived(evidenceFilter(studio.concepts, query, status));
  let selected = $derived(rows.find(item => item.id === selectedId));

  $effect(() => {
    const visibleRows = rows;
    if (!visibleRows.length) {
      selectedId = '';
    } else if (!visibleRows.some(item => item.id === selectedId)) {
      selectedId = visibleRows[0].id;
    }
  });
</script>

<section aria-labelledby="evidence-heading">
  <div class="view-intro">
    <span class="eyebrow">Prove</span>
    <h2 id="evidence-heading">Capability evidence without inflated claims</h2>
    <p>A check means the catalog links that evidence category. It does not silently upgrade partial or deferred capability status.</p>
  </div>

  <div class="mb-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
    <label class="relative block"><span class="sr-only">Search evidence</span><Search class="pointer-events-none absolute left-3 top-3 text-[var(--muted)]" size={17}/><input bind:value={query} type="search" placeholder="Search capability or limitation…" class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] py-2 pl-10 pr-3 text-sm outline-none focus:border-[var(--accent)]"/></label>
    <label><span class="sr-only">Evidence status</span><select bind:value={status} class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 text-sm"><option value="all">All statuses</option><option value="implemented">Implemented</option><option value="partial">Partial</option><option value="deferred">Deferred</option></select></label>
  </div>

  <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
    <div class="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
      <div class="border-b border-[var(--border)] px-4 py-3 text-xs text-[var(--muted)]"><strong class="text-[var(--text)]">{rows.length}</strong> of 66 capabilities</div>
      <div class="hidden overflow-x-auto md:block">
        <table class="w-full border-collapse text-left text-xs">
          <thead class="bg-[var(--bg)] text-[10px] uppercase tracking-wider text-[var(--muted)]"><tr><th class="p-3">Capability</th><th class="p-3">Status</th><th class="p-3 text-center">Code</th><th class="p-3 text-center">Tests</th><th class="p-3 text-center">Evidence</th></tr></thead>
          <tbody>
            {#if !rows.length}
              <tr><td colspan="5" class="p-6 text-center text-sm text-[var(--muted)]">No capabilities match the current filters.</td></tr>
            {/if}
            {#each rows as concept}
              <tr class="border-t border-[var(--border)] transition {selectedId === concept.id ? 'bg-[rgba(85,214,190,.08)]' : ''}">
                <td class="p-0"><button onclick={() => selectedId = concept.id} class="min-h-14 w-full p-3 text-left hover:bg-[rgba(85,214,190,.05)]"><strong class="block text-sm">{concept.title}</strong><span class="mt-1 block text-[10px] text-[var(--muted)]">{concept.module_id}</span></button></td>
                <td class="p-3"><span class="rounded-full px-2 py-1 font-mono text-[9px] uppercase" style={`color:${STATUS_META[concept.status].color};background:${STATUS_META[concept.status].color}14`}>{STATUS_META[concept.status].label}</span></td>
                {#each [concept.proof.code, concept.proof.tests, concept.proof.evidence] as proven}<td class="p-3 text-center">{#if proven}<Check class="mx-auto text-[var(--accent)]" size={16}/>{:else}<Minus class="mx-auto text-[var(--muted)]" size={16}/>{/if}</td>{/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div class="space-y-2 p-3 md:hidden">
        {#if !rows.length}<p class="p-3 text-center text-sm text-[var(--muted)]">No capabilities match the current filters.</p>{/if}
        {#each rows as concept}
          <button onclick={() => selectedId = concept.id} class="min-h-20 w-full rounded-xl border p-3 text-left {selectedId === concept.id ? 'border-[var(--accent)] bg-[rgba(85,214,190,.08)]' : 'border-[var(--border)] bg-[var(--bg)]'}">
            <div class="flex items-start justify-between gap-2"><strong class="text-sm">{concept.title}</strong><span class="rounded-full px-2 py-1 font-mono text-[9px] uppercase" style={`color:${STATUS_META[concept.status].color};background:${STATUS_META[concept.status].color}14`}>{STATUS_META[concept.status].label}</span></div>
            <span class="mt-2 block text-[10px] text-[var(--muted)]">Code {concept.proof.code ? '✓' : '—'} · Tests {concept.proof.tests ? '✓' : '—'} · Evidence {concept.proof.evidence ? '✓' : '—'}</span>
          </button>
        {/each}
      </div>
    </div>

    <aside class="h-fit rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 xl:sticky xl:top-4" aria-label="Selected evidence details">
      {#if selected}
        <span class="eyebrow">Evidence boundary</span><h3 class="mt-2 text-xl font-semibold">{selected.title}</h3><p class="mt-2 text-sm leading-6 text-[var(--secondary)]">{selected.limitations}</p>
        {#each [{title: 'Code', links: selected.sources}, {title: 'Tests', links: selected.tests}, {title: 'Evidence', links: selected.evidence}] as group}
          <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">{group.title}</h4>
          {#if group.links.length}<div class="space-y-2">{#each group.links as link}<a href={link.href} target="_blank" rel="noopener" class="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)]"><span class="truncate font-mono">{link.path}</span><ExternalLink class="shrink-0" size={13}/></a>{/each}</div>{:else}<p class="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted)]">No separate {group.title.toLowerCase()} mapping is recorded.</p>{/if}
        {/each}
      {:else}
        <p class="m-0 text-sm text-[var(--muted)]">No evidence details are available for the current filters.</p>
      {/if}
    </aside>
  </div>
</section>
