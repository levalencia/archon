<script lang="ts">
  import { ChevronDown, ChevronRight, ExternalLink, Target } from 'lucide-svelte';
  import { STATUS_META, conceptsForModule, type VisualLearningStudio } from '$lib/visual-learning';

  let { studio }: { studio: VisualLearningStudio } = $props();
  let selectedModule = $state('00-agent-anatomy');
  let module = $derived(studio.modules.find(item => item.id === selectedModule));
  let concepts = $derived(conceptsForModule(studio, selectedModule));
</script>

<section aria-labelledby="roadmap-heading">
  <div class="view-intro">
    <span class="eyebrow">Learn</span>
    <h2 id="roadmap-heading">A stable path from foundations to operations</h2>
    <p>Each phase answers one question. Move downward in learning order; expand a module only when you need its concepts.</p>
  </div>

  <div class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
    <div class="space-y-3">
      {#each studio.roadmap as phase, phaseIndex}
        <article class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 md:p-5">
          <div class="mb-4 flex gap-3">
            <span class="grid size-10 shrink-0 place-items-center rounded-full border border-[var(--accent)] bg-[rgba(85,214,190,.1)] font-mono text-sm text-[var(--accent)]">{phaseIndex + 1}</span>
            <div>
              <h3 class="m-0 text-lg font-semibold">{phase.title}</h3>
              <p class="mt-1 text-sm text-[var(--secondary)]">{phase.question}</p>
              <p class="mt-2 flex items-start gap-2 text-xs leading-5 text-[var(--muted)]"><Target class="mt-0.5 shrink-0" size={14}/>{phase.outcome}</p>
            </div>
          </div>
          <div class="grid gap-2 sm:grid-cols-2">
            {#each phase.module_ids as moduleId}
              {@const item = studio.modules.find(candidate => candidate.id === moduleId)}
              {#if item}
                <button onclick={() => selectedModule = moduleId} aria-pressed={selectedModule === moduleId} class="min-h-16 rounded-xl border p-3 text-left transition {selectedModule === moduleId ? 'border-[var(--accent)] bg-[rgba(85,214,190,.1)]' : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]'}">
                  <span class="font-mono text-[10px] uppercase tracking-wider text-[var(--muted)]">{moduleId.slice(0, 2)} · {item.concept_count} concepts</span>
                  <strong class="mt-1 flex items-center justify-between gap-2 text-sm"><span>{item.title.replace(/^Module\s+\d+\s*[—-]\s*/, '')}</span><ChevronRight size={15}/></strong>
                </button>
              {/if}
            {/each}
          </div>
        </article>
        {#if phaseIndex < studio.roadmap.length - 1}
          <div class="flex justify-center text-[var(--muted)]" aria-hidden="true"><ChevronDown size={20}/></div>
        {/if}
      {/each}
    </div>

    <aside class="h-fit rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 xl:sticky xl:top-4" aria-label="Selected module">
      {#if module}
        <span class="font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">Selected module</span>
        <h3 class="mt-2 text-xl font-semibold">{module.title}</h3>
        <p class="mt-2 text-sm leading-6 text-[var(--secondary)]">{module.summary}</p>
        <a href={module.href} target="_blank" rel="noopener" class="mt-3 flex min-h-11 items-center justify-between rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--text)] no-underline hover:border-[var(--accent)]">Open canonical module <ExternalLink size={14}/></a>
        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Concepts in this module</h4>
        {#if concepts.length}
          <div class="space-y-2">
            {#each concepts as concept}
              <a href={concept.detail_href} target="_blank" rel="noopener" class="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)]">
                <span>{concept.title}</span>
                <span class="shrink-0 rounded-full px-2 py-1 font-mono text-[9px] uppercase" style={`color:${STATUS_META[concept.status].color};background:${STATUS_META[concept.status].color}14`}>{STATUS_META[concept.status].label}</span>
              </a>
            {/each}
          </div>
        {:else}
          <p class="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted)]">This capstone module integrates prior concepts instead of owning separate catalog entries.</p>
        {/if}
      {/if}
    </aside>
  </div>
</section>
