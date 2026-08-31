<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { BookOpen, GitBranch, Headphones, Layers, Map, Presentation, TableProperties } from 'lucide-svelte';
  import ArchitectureView from './ArchitectureView.svelte';
  import EvidenceView from './EvidenceView.svelte';
  import MediaView from './MediaView.svelte';
  import RoadmapView from './RoadmapView.svelte';
  import StoriesView from './StoriesView.svelte';
  import { loadVisualLearningStudio, type VisualLearningStudio } from '$lib/visual-learning';

  type StudioView = 'roadmap' | 'stories' | 'architecture' | 'evidence' | 'present' | 'listen' | 'study';
  const views: Array<{ id: StudioView; label: string; question: string; icon: typeof Map }> = [
    { id: 'roadmap', label: 'Roadmap', question: 'What should I learn next?', icon: Map },
    { id: 'stories', label: 'Stories', question: 'What happens during a workflow?', icon: GitBranch },
    { id: 'architecture', label: 'Architecture', question: 'How is the system structured?', icon: Layers },
    { id: 'evidence', label: 'Evidence', question: 'What is actually proven?', icon: TableProperties },
    { id: 'present', label: 'Present', question: 'How do I explain it visually?', icon: Presentation },
    { id: 'listen', label: 'Listen', question: 'How can I review through audio?', icon: Headphones },
    { id: 'study', label: 'Study', question: 'How can I test comprehension?', icon: BookOpen },
  ];

  let studio = $state<VisualLearningStudio | null>(null);
  let loading = $state(true);
  let error = $state('');

  function parseView(value: string | null): StudioView {
    const requested = value as StudioView | null;
    return requested && views.some(view => view.id === requested) ? requested : 'roadmap';
  }

  let activeView = $derived(parseView(page.url.searchParams.get('view')));

  onMount(() => {
    void loadVisualLearningStudio()
      .then(payload => { studio = payload; loading = false; })
      .catch(cause => {
        error = cause instanceof Error ? cause.message : 'Unable to load Visual Learning Studio';
        loading = false;
      });
  });
</script>

<div class="min-h-full bg-[var(--bg)] text-[var(--text)]">
  <header class="border-b border-[var(--border)] bg-[radial-gradient(circle_at_top_left,rgba(85,214,190,.12),transparent_38%),var(--panel)] px-4 py-6 md:px-8">
    <div class="mx-auto flex max-w-[1500px] flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
      <div class="max-w-3xl"><span class="eyebrow">Archon Visual Learning Studio</span><h1 class="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">Choose the view that matches your question</h1><p class="mt-2 max-w-2xl text-sm leading-6 text-[var(--secondary)]">Stable roadmaps, explicit flows, layered architecture, evidence boundaries, and NotebookLM media recipes — all derived from canonical project sources.</p></div>
      {#if studio}<div class="grid grid-cols-4 gap-2" aria-label="Visual Learning Studio summary"><div class="metric"><strong>{studio.stats.concepts}</strong><span>Concepts</span></div><div class="metric"><strong>{studio.stats.modules}</strong><span>Modules</span></div><div class="metric"><strong>{studio.stats.stories}</strong><span>Stories</span></div><div class="metric"><strong>{studio.stats.notebooks}</strong><span>Notebooks</span></div></div>{/if}
    </div>
  </header>

  <nav class="sticky top-0 z-30 border-b border-[var(--border)] bg-[rgba(8,11,16,.94)] px-3 py-2 backdrop-blur" aria-label="Visual Learning Studio views">
    <div class="mx-auto flex max-w-[1500px] gap-2 overflow-x-auto pb-1">
      {#each views as view}
        <a href={`/learn?view=${view.id}`} aria-current={activeView === view.id ? 'page' : undefined} class="flex min-h-14 min-w-32 shrink-0 items-center gap-2 rounded-xl border px-3 text-left no-underline transition {activeView === view.id ? 'border-[var(--accent)] bg-[rgba(85,214,190,.1)] text-[var(--text)]' : 'border-[var(--border)] bg-[var(--panel)] text-[var(--muted)] hover:border-[var(--accent)]'}"><view.icon size={17}/><span><strong class="block text-xs">{view.label}</strong><small class="mt-0.5 block max-w-40 truncate text-[9px]">{view.question}</small></span></a>
      {/each}
    </div>
  </nav>

  <main class="mx-auto max-w-[1500px] p-3 md:p-6">
    {#if loading}<div class="grid min-h-[55vh] place-items-center rounded-2xl border border-[var(--border)] bg-[var(--panel)] text-sm text-[var(--muted)]">Loading structured learning views…</div>
    {:else if error}<div role="alert" class="rounded-xl border border-[rgba(255,107,114,.4)] bg-[rgba(255,107,114,.08)] p-4 text-sm text-[var(--danger)]">{error}</div>
    {:else if studio}
      {#if activeView === 'roadmap'}<RoadmapView {studio}/>
      {:else if activeView === 'stories'}<StoriesView {studio}/>
      {:else if activeView === 'architecture'}<ArchitectureView {studio}/>
      {:else if activeView === 'evidence'}<EvidenceView {studio}/>
      {:else if activeView === 'present'}<MediaView {studio} mode="present"/>
      {:else if activeView === 'listen'}<MediaView {studio} mode="listen"/>
      {:else}<MediaView {studio} mode="study"/>
      {/if}
    {/if}
  </main>
</div>

<style>
  :global(.view-intro) { margin-bottom: 1.25rem; max-width: 52rem; }
  :global(.view-intro h2) { margin: .35rem 0 0; font-size: clamp(1.45rem, 3vw, 2rem); line-height: 1.2; }
  :global(.view-intro p) { margin: .55rem 0 0; color: var(--secondary); font-size: .875rem; line-height: 1.65; }
  :global(.eyebrow) { color: var(--accent); font-family: var(--font-mono); font-size: .65rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
  .metric { min-width: 74px; border: 1px solid var(--border); border-radius: .75rem; background: rgba(8,11,16,.55); padding: .55rem .7rem; text-align: center; }
  .metric strong { display: block; font-family: var(--font-mono); font-size: 1.1rem; }
  .metric span { color: var(--muted); font-size: .58rem; letter-spacing: .08em; text-transform: uppercase; }
</style>
