<script lang="ts">
  import { BookOpen, Download, ExternalLink, FileStack, Headphones, Presentation, Sparkles } from 'lucide-svelte';
  import type { NotebookRecipe, VisualLearningStudio } from '$lib/visual-learning';

  type MediaMode = 'present' | 'listen' | 'study';
  let { studio, mode }: { studio: VisualLearningStudio; mode: MediaMode } = $props();

  const modeMeta = {
    present: {
      eyebrow: 'Present', title: 'Explain Archon visually',
      description: 'Generate slide decks, whiteboard videos, and infographics from focused source packs.',
      artifacts: ['slide-deck', 'video', 'infographic'], icon: Presentation,
    },
    listen: {
      eyebrow: 'Listen', title: 'Review Archon through audio',
      description: 'Generate deep dives and technical debates without replacing canonical written evidence.',
      artifacts: ['audio'], icon: Headphones,
    },
    study: {
      eyebrow: 'Study', title: 'Practice retrieval and comprehension',
      description: 'Generate focused mind maps, flashcards, and scenario quizzes for one domain at a time.',
      artifacts: ['mind-map', 'flashcards', 'quiz'], icon: BookOpen,
    },
  } as const;

  let selectedId = $state('system-overview');
  let meta = $derived(modeMeta[mode]);
  let available = $derived(
    studio.notebooklm.notebooks.filter(notebook => notebook.artifacts.some(item => meta.artifacts.includes(item as never))),
  );
  let selected: NotebookRecipe | undefined = $derived(
    available.find(item => item.id === selectedId) ?? available[0],
  );

  $effect(() => {
    if (available.length && !available.some(item => item.id === selectedId)) selectedId = available[0].id;
  });

  function label(value: string): string {
    return value.split('-').map(part => part[0]?.toUpperCase() + part.slice(1)).join(' ');
  }
</script>

<section aria-labelledby="media-heading">
  <div class="view-intro">
    <span class="eyebrow">{meta.eyebrow}</span>
    <h2 id="media-heading">{meta.title}</h2>
    <p>{meta.description}</p>
  </div>

  <div class="mb-4 flex items-start gap-3 rounded-xl border border-[rgba(240,189,98,.35)] bg-[rgba(240,189,98,.07)] p-4 text-sm text-[var(--secondary)]">
    <Sparkles class="mt-0.5 shrink-0 text-[var(--warning)]" size={18}/><p class="m-0"><strong class="text-[var(--text)]">Prepared, not yet generated.</strong> Source packs and prompts are reproducible. NotebookLM artifacts require Luis to upload the pack and generate them in his Google account.</p>
  </div>

  <div class="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
    <aside class="h-fit rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-3" aria-label="NotebookLM notebooks">
      <h3 class="px-2 pb-2 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Choose a focused notebook</h3>
      <div class="space-y-2">
        {#each available as notebook}
          <button onclick={() => selectedId = notebook.id} aria-pressed={selected?.id === notebook.id} class="min-h-20 w-full rounded-xl border p-3 text-left transition {selected?.id === notebook.id ? 'border-[var(--accent)] bg-[rgba(85,214,190,.09)]' : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]'}">
            <strong class="block text-sm">{notebook.title.replace('Archon — ', '')}</strong><span class="mt-1 block text-xs text-[var(--muted)]">{notebook.source_count} sources</span>
          </button>
        {/each}
      </div>
    </aside>

    {#if selected}
      <div class="space-y-4">
        <article class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 md:p-5">
          <span class="eyebrow">Notebook recipe</span><h3 class="mt-2 text-xl font-semibold">{selected.title}</h3><p class="mt-2 text-sm leading-6 text-[var(--secondary)]">{selected.purpose}</p>
          <div class="mt-4 grid gap-2 sm:grid-cols-3">
            {#each meta.artifacts.filter(item => selected?.artifacts.includes(item)) as artifact}
              <div class="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3"><span class="font-mono text-[10px] uppercase tracking-wider text-[var(--accent)]">Ready recipe</span><strong class="mt-2 block text-sm">{label(artifact)}</strong></div>
            {/each}
          </div>
        </article>

        <div class="grid gap-4 lg:grid-cols-2">
          <article class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4">
            <div class="flex items-center gap-2"><FileStack class="text-[var(--accent)]" size={18}/><h3 class="m-0 text-sm font-semibold">Source pack</h3></div>
            <p class="mt-2 text-xs leading-5 text-[var(--muted)]">Generated outside Git from an explicit allowlist. Upload the truth-boundary source first, then numbered files.</p>
            <code class="mt-3 block overflow-x-auto rounded-lg bg-[var(--bg)] p-3 text-[10px] text-[var(--secondary)]">python scripts/build-notebooklm-source-packs.py</code>
            <div class="mt-3 max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
              {#each selected.sources as source}<div class="truncate font-mono text-[10px] text-[var(--muted)]">{source}</div>{/each}
            </div>
          </article>

          <article class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4">
            <div class="flex items-center gap-2"><Download class="text-[var(--accent)]" size={18}/><h3 class="m-0 text-sm font-semibold">Generation instructions</h3></div>
            <ol class="mt-3 space-y-2 pl-5 text-xs leading-5 text-[var(--secondary)]"><li>Create a notebook with the exact recipe title.</li><li>Upload the generated truth-boundary file first.</li><li>Upload every numbered source file from this pack.</li><li>Copy the matching prompt from the promptbook.</li><li>Generate one artifact and score it before making variants.</li></ol>
            <a href={studio.notebooklm.promptbook_href} target="_blank" rel="noopener" class="mt-4 flex min-h-11 items-center justify-between rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--text)] no-underline hover:border-[var(--accent)]">Open NotebookLM promptbook <ExternalLink size={14}/></a>
            <a href={studio.notebooklm.runbook_href} target="_blank" rel="noopener" class="mt-2 flex min-h-11 items-center justify-between rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--text)] no-underline hover:border-[var(--accent)]">Open step-by-step runbook <ExternalLink size={14}/></a>
          </article>
        </div>
      </div>
    {/if}
  </div>
</section>
