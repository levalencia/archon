<script lang="ts">
  import { ArrowDown, ExternalLink } from 'lucide-svelte';
  import { RELATION_META, type VisualLearningStudio } from '$lib/visual-learning';

  let { studio }: { studio: VisualLearningStudio } = $props();
  let selectedId = $state('browser-workbench');
  let selected = $derived(
    studio.architecture.layers.flatMap(layer => layer.components).find(item => item.id === selectedId),
  );
  let relations = $derived(
    studio.architecture.relations.filter(item => item.source === selectedId || item.target === selectedId),
  );

  function componentTitle(id: string): string {
    return studio.architecture.layers
      .flatMap(layer => layer.components)
      .find(component => component.id === id)?.title ?? id;
  }
</script>

<section aria-labelledby="architecture-heading">
  <div class="view-intro">
    <span class="eyebrow">Understand structure</span>
    <h2 id="architecture-heading">Five stable architecture layers</h2>
    <p>Components never move. Select one to inspect only its typed incoming and outgoing relationships.</p>
  </div>

  <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
    <div class="space-y-3">
      {#each studio.architecture.layers as layer, index}
        <section class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4" aria-labelledby={`${layer.id}-heading`}>
          <div class="mb-3">
            <span class="font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">Layer {index + 1}</span>
            <h3 id={`${layer.id}-heading`} class="mt-1 text-lg font-semibold">{layer.title}</h3>
            <p class="mt-1 text-xs leading-5 text-[var(--muted)]">{layer.description}</p>
          </div>
          <div class="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {#each layer.components as component}
              <button onclick={() => selectedId = component.id} aria-pressed={selectedId === component.id} class="min-h-28 rounded-xl border p-3 text-left transition {selectedId === component.id ? 'border-[var(--accent)] bg-[rgba(85,214,190,.1)]' : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]'}">
                <strong class="block text-sm">{component.title}</strong>
                <span class="mt-2 block text-xs leading-5 text-[var(--muted)]">{component.responsibility}</span>
              </button>
            {/each}
          </div>
        </section>
        {#if index < studio.architecture.layers.length - 1}
          <div class="flex items-center justify-center gap-2 text-[var(--muted)]" aria-hidden="true"><ArrowDown size={18}/><span class="font-mono text-[9px] uppercase tracking-wider">controlled flow</span></div>
        {/if}
      {/each}
    </div>

    <aside class="h-fit rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 xl:sticky xl:top-4" aria-label="Selected architecture component">
      {#if selected}
        <span class="eyebrow">Selected component</span>
        <h3 class="mt-2 text-xl font-semibold">{selected.title}</h3>
        <p class="mt-2 text-sm leading-6 text-[var(--secondary)]">{selected.responsibility}</p>

        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Typed relationships</h4>
        <div class="space-y-2">
          {#each relations as relation}
            {@const outgoing = relation.source === selectedId}
            <div class="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3">
              <div class="flex items-center justify-between gap-2">
                <span class="rounded-full px-2 py-1 font-mono text-[9px] font-bold" style={`color:${RELATION_META[relation.type]?.color ?? '#94a3b8'};background:${RELATION_META[relation.type]?.color ?? '#94a3b8'}14`}>{relation.type}</span>
                <span class="text-[10px] uppercase tracking-wider text-[var(--muted)]">{outgoing ? 'Outgoing' : 'Incoming'}</span>
              </div>
              <p class="mb-0 mt-2 text-xs text-[var(--secondary)]">{outgoing ? selected.title : componentTitle(relation.source)} → <strong>{relation.label}</strong> → {outgoing ? componentTitle(relation.target) : selected.title}</p>
            </div>
          {/each}
        </div>

        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Grounding concepts</h4>
        <div class="space-y-2">
          {#each selected.concept_ids as conceptId}
            {@const concept = studio.concepts.find(item => item.id === conceptId)}
            {#if concept}
              <a href={concept.detail_href} target="_blank" rel="noopener" class="flex min-h-11 items-center justify-between rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)]"><span>{concept.title}</span><ExternalLink size={13}/></a>
            {/if}
          {/each}
        </div>
      {/if}
    </aside>
  </div>
</section>
