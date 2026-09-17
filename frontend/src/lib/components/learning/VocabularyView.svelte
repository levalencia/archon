<script lang="ts">
  import { BookOpen, ExternalLink, PlayCircle, Search } from 'lucide-svelte';
  import {
    vocabularyFilter,
    type VisualLearningStudio,
    type VocabularyLevel,
  } from '$lib/visual-learning';

  let { studio }: { studio: VisualLearningStudio } = $props();

  let query = $state('');
  let category = $state('all');
  let level = $state<VocabularyLevel | 'all'>('all');
  let selectedId = $state('');
  let categories = $derived([...new Set(studio.vocabulary.map(entry => entry.category))].sort());
  let rows = $derived(vocabularyFilter(studio.vocabulary, query, category, level));
  let selected = $derived(rows.find(entry => entry.id === selectedId));

  $effect(() => {
    const visibleRows = rows;
    if (!visibleRows.length) selectedId = '';
    else if (!visibleRows.some(entry => entry.id === selectedId)) selectedId = visibleRows[0].id;
  });

</script>

<section class="pb-24" aria-labelledby="glossary-heading">
  <div class="view-intro">
    <span class="eyebrow">Understand the words</span>
    <h2 id="glossary-heading">Canonical Cogentrex vocabulary</h2>
    <p>Start with a plain-English definition, then connect the term to the actual Cogentrex boundary, concept page, and available learning media.</p>
  </div>

  <div class="mb-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px_180px]">
    <label class="relative block">
      <span class="sr-only">Search vocabulary</span>
      <Search class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]" size={17}/>
      <input bind:value={query} type="search" placeholder="Search term, alias, definition, or concept…" class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] py-2 pl-10 pr-3 text-sm outline-none focus:border-[var(--accent)]"/>
    </label>
    <label><span class="sr-only">Vocabulary category</span><select bind:value={category} class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 text-sm"><option value="all">All categories</option>{#each categories as item}<option value={item}>{item.replaceAll('-', ' ')}</option>{/each}</select></label>
    <label><span class="sr-only">Vocabulary level</span><select bind:value={level} class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 text-sm"><option value="all">All levels</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
  </div>

  <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
    <div class="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
      <div class="border-b border-[var(--border)] px-4 py-3 text-xs text-[var(--muted)]"><strong class="text-[var(--text)]">{rows.length}</strong> of {studio.stats.vocabulary_terms} terms · {studio.stats.vocabulary_aliases} aliases</div>
      <div class="max-h-[70vh] overflow-y-auto p-3">
        {#if !rows.length}<p class="p-6 text-center text-sm text-[var(--muted)]">No vocabulary terms match the current filters.</p>{/if}
        <div class="grid gap-2 md:grid-cols-2">
          {#each rows as entry}
            <button onclick={() => selectedId = entry.id} class="min-h-24 rounded-xl border p-3 text-left transition {selectedId === entry.id ? 'border-[var(--accent)] bg-[var(--accent-glow)] shadow-[0_0_18px_var(--cogentrex-orange-glow)]' : 'border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]'}">
              <div class="flex items-start justify-between gap-2"><strong class="text-sm">{entry.term}</strong><span class="rounded-full bg-[var(--panel)] px-2 py-1 font-mono text-[9px] uppercase text-[var(--accent)]">{entry.level}</span></div>
              {#if entry.aliases.length}<span class="mt-1 block truncate text-[10px] text-[var(--muted)]">Also: {entry.aliases.join(', ')}</span>{/if}
              <span class="mt-2 line-clamp-2 block text-xs leading-5 text-[var(--secondary)]">{entry.definition}</span>
            </button>
          {/each}
        </div>
      </div>
    </div>

    <aside class="h-fit rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5 xl:sticky xl:top-4" aria-label="Selected vocabulary details">
      {#if selected}
        <span class="eyebrow">{selected.category.replaceAll('-', ' ')}</span>
        <h3 class="mt-2 text-2xl font-semibold">{selected.term}</h3>
        {#if selected.aliases.length}<p class="mt-1 text-xs text-[var(--muted)]">Also called {selected.aliases.join(', ')}</p>{/if}
        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Plain-English meaning</h4>
        <p class="text-sm leading-6 text-[var(--secondary)]">{selected.definition}</p>
        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">In Cogentrex</h4>
        <p class="text-sm leading-6 text-[var(--secondary)]">{selected.cogentrex}</p>
        <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Canonical reading</h4>
        <div class="space-y-2">{#each selected.learn_more as link}<a href={link.href} target="_blank" rel="noopener" class="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)]"><span class="flex items-center gap-2 truncate"><BookOpen size={14}/><span class="truncate">{link.path}</span></span><ExternalLink class="shrink-0" size={13}/></a>{/each}</div>
        {#if selected.media_refs.length}
          <h4 class="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">Watch or listen</h4>
          <div class="space-y-2">{#each selected.media_refs as media}<a href={media.href} class="flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)]"><PlayCircle size={14}/>{media.label}</a>{/each}</div>
        {/if}
      {:else}
        <p class="m-0 text-sm text-[var(--muted)]">No vocabulary details are available for the current filters.</p>
      {/if}
    </aside>
  </div>
</section>
