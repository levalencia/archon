<script lang="ts">
  import { onMount } from 'svelte';
  import { Download, ExternalLink, RefreshCw } from 'lucide-svelte';
  import {
    getLearningArtifact,
    getMediaAccess,
    loadLearningLibrary,
    type LearningArtifactDetail,
    type LearningArtifactSummary,
    type LearningLibraryCatalog,
  } from '$lib/learning-artifacts';
  import PresentationPlayer from './PresentationPlayer.svelte';
  import DiagramViewer from './DiagramViewer.svelte';
  import InfographicViewer from './InfographicViewer.svelte';
  import AudioLessonPlayer from './AudioLessonPlayer.svelte';
  import MindMapViewer from './MindMapViewer.svelte';
  import FlashcardPlayer from './FlashcardPlayer.svelte';
  import QuizPlayer from './QuizPlayer.svelte';
  import StudyGuideViewer from './StudyGuideViewer.svelte';
  import VideoLessonPlayer from './VideoLessonPlayer.svelte';

  type MediaMode = 'present' | 'listen' | 'study';
  let { mode }: { mode: MediaMode } = $props();
  const types = {
    present: ['deck', 'diagram', 'infographic', 'video'],
    listen: ['audio', 'podcast'],
    study: ['mind-map', 'flashcards', 'quiz', 'study-guide'],
  } as const;
  const copy = {
    present: ['Present', 'Explain Cogentrex visually', 'Open an evidence-grounded deck, diagram, infographic, or explainer.'],
    listen: ['Listen', 'Review Cogentrex through English audio', 'Use narrated lessons and transcripts without leaving the learning studio.'],
    study: ['Study', 'Practice retrieval and comprehension', 'Explore a focused mind map, flashcards, scenarios, and a study guide.'],
  } as const;

  let catalog = $state<LearningLibraryCatalog | null>(null);
  let selectedPack = $state('request-lifecycle');
  let selectedId = $state('');
  let detail = $state<LearningArtifactDetail | null>(null);
  let mediaUrl = $state('');
  let loading = $state(true);
  let error = $state('');
  let visibleArtifacts = $derived(
    catalog?.packs.find(pack => pack.id === selectedPack)?.artifacts.filter(item => (types[mode] as readonly string[]).includes(item.type)) ?? [],
  );
  let selected = $derived(visibleArtifacts.find(item => item.id === selectedId) ?? visibleArtifacts[0]);

  async function loadArtifact(artifact: LearningArtifactSummary | undefined) {
    if (!artifact) { detail = null; mediaUrl = ''; return; }
    selectedId = artifact.id; detail = null; mediaUrl = ''; error = '';
    try {
      detail = await getLearningArtifact(artifact.id);
      if (['audio', 'podcast', 'video'].includes(artifact.type)) {
        mediaUrl = (await getMediaAccess(artifact.id)).url;
      }
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Unable to load learning artifact';
    }
  }

  async function selectPack(packId: string) {
    selectedPack = packId;
    const first = catalog?.packs.find(pack => pack.id === packId)?.artifacts.find(item => (types[mode] as readonly string[]).includes(item.type));
    await loadArtifact(first);
  }

  async function openPrimary() {
    if (!selected) return;
    const access = await getMediaAccess(selected.id);
    window.open(access.url, '_blank', 'noopener');
  }

  onMount(async () => {
    try {
      catalog = await loadLearningLibrary();
      const first = catalog.packs.find(pack => pack.id === selectedPack)?.artifacts.find(item => (types[mode] as readonly string[]).includes(item.type));
      await loadArtifact(first);
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'Learning library unavailable';
    } finally {
      loading = false;
    }
  });

  $effect(() => {
    mode;
    if (!catalog) return;
    const first = visibleArtifacts[0];
    if (first && !visibleArtifacts.some(item => item.id === selectedId)) void loadArtifact(first);
  });
</script>

<section aria-labelledby="library-heading">
  <div class="view-intro"><span class="eyebrow">{copy[mode][0]}</span><h2 id="library-heading">{copy[mode][1]}</h2><p>{copy[mode][2]}</p></div>
  {#if loading}<div class="state" aria-busy="true">Loading the published learning library…</div>
  {:else if error && !catalog}<div class="state warning" role="status"><strong>Learning media is not published in this runtime.</strong><span>{error}</span><span>The evidence-grounded generation recipes remain available in the repository.</span></div>
  {:else if catalog}
    <nav class="pack-tabs" aria-label="Learning packs">
      {#each catalog.packs as pack}
        <button onclick={() => selectPack(pack.id)} aria-pressed={selectedPack === pack.id}>{pack.title}</button>
      {/each}
    </nav>
    <div class="layout">
      <aside aria-label="Published learning artifacts"><div class="pack"><span class="eyebrow">Learning pack</span><strong>{catalog.packs.find(pack=>pack.id===selectedPack)?.title}</strong></div>{#each visibleArtifacts as artifact}<button onclick={()=>loadArtifact(artifact)} aria-pressed={selected?.id===artifact.id}><span>{artifact.type.replaceAll('-', ' ')}</span><strong>{artifact.title.replace('Cogentrex Request Lifecycle — ', '')}</strong><small>{artifact.status} · English</small></button>{/each}</aside>
      <div class="viewer">
        {#if error}<div class="state warning" role="alert">{error}</div>{/if}
        {#if selected}<header class="artifact-head"><div><span class="eyebrow">{selected.type.replaceAll('-', ' ')}</span><h3>{selected.title}</h3><p>{selected.status === 'stale' ? 'Published artifact — source changes detected.' : selected.status === 'review-ready' ? 'Generated and technically verified — Luis review pending.' : 'Published and checksum-verified.'}</p></div><button onclick={openPrimary} aria-label="Open or download primary artifact"><Download size={15}/> {['deck','diagram','infographic','audio','video'].includes(selected.type) ? 'Open file' : 'Download data'}</button></header>{/if}
        {#if detail?.content}
          {@const content = detail.content as any}
          {#if selected?.type === 'deck'}<PresentationPlayer {content} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'diagram'}<DiagramViewer {content} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'infographic'}<InfographicViewer {content} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'audio' || selected?.type === 'podcast'}{#if mediaUrl}<AudioLessonPlayer title={selected.title} {mediaUrl} {content} limitations={selected.limitations} sourceCommit={selected.source_commit}/>{/if}
          {:else if selected?.type === 'mind-map'}<MindMapViewer root={content.root} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'flashcards'}<FlashcardPlayer cards={content.cards} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'quiz'}<QuizPlayer questions={content.questions} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'study-guide'}<StudyGuideViewer sections={content.sections} sourceCommit={selected.source_commit}/>
          {:else if selected?.type === 'video'}{#if mediaUrl}<VideoLessonPlayer title={selected.title} {mediaUrl} {content} limitations={selected.limitations} sourceCommit={selected.source_commit} durationSeconds={selected.duration_seconds}/>{/if}
          {:else}<div class="state">This accepted artifact can be opened as a file.</div>{/if}
        {:else if selected}<div class="state"><RefreshCw size={18}/> Loading {selected.title}…</div>
        {:else}<div class="state">No accepted {mode} artifacts are available for this pack.</div>{/if}
        {#if selected}<details class="provenance"><summary>Provenance and limitations</summary><p>Source commit <code>{selected.source_commit.slice(0,12)}</code> · SHA-256 <code>{selected.sha256.slice(0,16)}…</code></p><ul>{#each selected.limitations as item}<li>{item}</li>{/each}</ul></details>{/if}
      </div>
    </div>
  {/if}
</section>

<style>
.pack-tabs{display:flex;gap:.5rem;overflow-x:auto;margin:0 0 1rem;padding:.25rem}.pack-tabs button{flex:0 0 auto;min-height:42px;border:1px solid var(--border);border-radius:.7rem;background:var(--panel);color:var(--secondary);padding:.65rem .85rem}.pack-tabs button[aria-pressed="true"]{border-color:var(--accent);color:var(--text);box-shadow:0 0 18px var(--cogentrex-orange-glow)}.layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:1rem}.layout>aside{display:flex;flex-direction:column;gap:.55rem}.pack,.layout>aside button,.viewer,.state{border:1px solid var(--border);border-radius:.85rem;background:var(--panel);padding:1rem}.pack strong{display:block;margin-top:.4rem}.layout>aside button{text-align:left;color:var(--text)}.layout>aside button[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-glow);box-shadow:0 0 18px var(--cogentrex-orange-glow)}.layout>aside button span{font:700 .6rem var(--font-mono);color:var(--accent);text-transform:uppercase}.layout>aside button strong,.layout>aside button small{display:block;margin-top:.3rem}.layout>aside button small{color:var(--muted)}.viewer{min-width:0}.artifact-head{display:flex;justify-content:space-between;align-items:start;gap:1rem;margin-bottom:1rem}.artifact-head h3{font-size:1.4rem;margin:.35rem 0}.artifact-head p{color:var(--muted);font-size:.75rem}.artifact-head button{display:flex;align-items:center;gap:.4rem;min-height:42px;border:1px solid var(--border);border-radius:.6rem;background:var(--bg);color:var(--text);padding:.6rem}.state{display:flex;align-items:center;gap:.5rem;color:var(--muted);min-height:100px}.state.warning{flex-direction:column;align-items:flex-start;border-color:rgba(240,189,98,.4);background:rgba(240,189,98,.06);color:var(--warning)}.provenance{margin-top:1rem;border-top:1px solid var(--border);padding-top:1rem;color:var(--muted);font-size:.75rem}.provenance code{font-size:.68rem}@media(max-width:850px){.layout{grid-template-columns:1fr}.layout>aside{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){.layout>aside{grid-template-columns:1fr}.artifact-head{display:block}.artifact-head button{margin-top:.75rem;width:100%;justify-content:center}}
</style>
