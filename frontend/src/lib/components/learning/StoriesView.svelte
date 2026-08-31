<script lang="ts">
  import { ArrowDown, ArrowRight, ChevronLeft, ChevronRight, ExternalLink } from 'lucide-svelte';
  import type { VisualLearningStudio } from '$lib/visual-learning';

  let { studio }: { studio: VisualLearningStudio } = $props();
  let storyId = $state('request-lifecycle');
  let stepIndex = $state(0);
  let story = $derived(studio.stories.find(item => item.id === storyId) ?? studio.stories[0]);
  let step = $derived(story?.steps[stepIndex]);

  function chooseStory(id: string) {
    storyId = id;
    stepIndex = 0;
  }

  function move(delta: number) {
    if (!story) return;
    stepIndex = Math.max(0, Math.min(story.steps.length - 1, stepIndex + delta));
  }
</script>

<section aria-labelledby="stories-heading">
  <div class="view-intro">
    <span class="eyebrow">Understand behavior</span>
    <h2 id="stories-heading">Follow one flow at a time</h2>
    <p>Every scene has one direction, one labeled relationship, and a clear explanation. No edge changes meaning between steps.</p>
  </div>

  <div class="mb-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-5" aria-label="Available guided stories">
    {#each studio.stories as item}
      <button onclick={() => chooseStory(item.id)} aria-pressed={storyId === item.id} class="min-h-16 rounded-xl border p-3 text-left transition {storyId === item.id ? 'border-[var(--accent)] bg-[rgba(85,214,190,.1)]' : 'border-[var(--border)] bg-[var(--panel)] hover:border-[var(--accent)]'}">
        <strong class="block text-sm">{item.title}</strong>
        <span class="mt-1 block text-xs text-[var(--muted)]">{item.steps.length} explicit steps</span>
      </button>
    {/each}
  </div>

  {#if story && step}
    <article class="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
      <header class="border-b border-[var(--border)] p-4 md:p-5">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <span class="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--warning)]">Step {stepIndex + 1} of {story.steps.length}</span>
            <h3 class="mt-1 text-xl font-semibold">{story.title}</h3>
            <p class="mt-1 max-w-3xl text-sm text-[var(--secondary)]">{story.description}</p>
          </div>
          <div class="flex gap-2">
            <button onclick={() => move(-1)} disabled={stepIndex === 0} aria-label="Previous story step" class="grid size-11 place-items-center rounded-lg border border-[var(--border)] disabled:opacity-30"><ChevronLeft size={18}/></button>
            <button onclick={() => move(1)} disabled={stepIndex === story.steps.length - 1} aria-label="Next story step" class="grid size-11 place-items-center rounded-lg border border-[var(--border)] disabled:opacity-30"><ChevronRight size={18}/></button>
          </div>
        </div>
        <div class="mt-4 flex gap-1" aria-label="Story progress">
          {#each story.steps as _, index}
            <button onclick={() => stepIndex = index} aria-label={`Go to step ${index + 1}`} aria-current={index === stepIndex ? 'step' : undefined} class="h-2 min-h-0 flex-1 rounded-full border-0 p-0 {index <= stepIndex ? 'bg-[var(--accent)]' : 'bg-[var(--border)]'}"></button>
          {/each}
        </div>
      </header>

      <div class="grid gap-5 p-4 md:p-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div>
          <h4 class="text-center text-2xl font-semibold">{step.title}</h4>
          <div class="mx-auto mt-8 flex max-w-4xl flex-col items-stretch justify-center gap-3 md:flex-row md:items-center">
            <div class="flex min-h-36 flex-1 items-center justify-center rounded-2xl border border-[rgba(127,167,255,.35)] bg-[rgba(127,167,255,.08)] p-5 text-center">
              <div><span class="font-mono text-[10px] uppercase tracking-wider text-[#9bb9ff]">From</span><strong class="mt-2 block text-lg">{step.from}</strong></div>
            </div>
            <div class="flex shrink-0 flex-col items-center justify-center gap-2 px-2 text-[var(--warning)]">
              <ArrowRight class="hidden md:block" size={34}/><ArrowDown class="md:hidden" size={34}/>
              <span class="max-w-40 rounded-full border border-[rgba(240,189,98,.35)] bg-[rgba(240,189,98,.08)] px-3 py-1 text-center font-mono text-[10px] font-bold uppercase tracking-wider">{step.relationship}</span>
            </div>
            <div class="flex min-h-36 flex-1 items-center justify-center rounded-2xl border border-[rgba(85,214,190,.35)] bg-[rgba(85,214,190,.08)] p-5 text-center">
              <div><span class="font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">To</span><strong class="mt-2 block text-lg">{step.to}</strong></div>
            </div>
          </div>
          <div class="mx-auto mt-6 max-w-3xl rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4">
            <span class="font-mono text-[10px] uppercase tracking-wider text-[var(--muted)]">What happens</span>
            <p class="mb-0 mt-2 text-sm leading-7 text-[var(--secondary)]">{step.explanation}</p>
          </div>
        </div>

        <aside class="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-4" aria-label="Concepts for current story step">
          <h4 class="m-0 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Concepts in this step</h4>
          <div class="mt-3 space-y-2">
            {#each step.concept_ids as conceptId}
              {@const concept = studio.concepts.find(item => item.id === conceptId)}
              {#if concept}
                <a href={concept.detail_href} target="_blank" rel="noopener" class="flex min-h-12 items-center justify-between gap-3 rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--secondary)] no-underline hover:border-[var(--accent)] hover:text-[var(--text)]"><span>{concept.title}</span><ExternalLink class="shrink-0" size={13}/></a>
              {/if}
            {/each}
          </div>
          <p class="mb-0 mt-4 text-xs leading-5 text-[var(--muted)]">The relationship label above describes this runtime step only. It is not a course prerequisite or an inferred dependency.</p>
        </aside>
      </div>
    </article>
  {/if}
</section>
