<script lang="ts">
  import SourceLinks from './SourceLinks.svelte';
  import type { EdgeTeaching, NodeTeaching } from '$lib/learning-teaching';
  import type { SourceReference } from '$lib/source-links';

  let {
    eyebrow,
    title,
    summary,
    nodeTeaching,
    edgeTeaching,
    moduleDetails,
    sources = [],
    sourceCommit,
  }: {
    eyebrow: string;
    title: string;
    summary?: string;
    nodeTeaching?: NodeTeaching;
    edgeTeaching?: EdgeTeaching;
    moduleDetails?: string;
    sources?: SourceReference[];
    sourceCommit: string;
  } = $props();
</script>

<article class="teaching-inspector" aria-live="polite">
  <header>
    <span class="eyebrow">{eyebrow}</span>
    <h4>{title}</h4>
    {#if summary}<p class="summary">{summary}</p>{/if}
  </header>

  {#if nodeTeaching}
    <div class="teaching-grid">
      <section class="wide"><h5>What it is</h5><p>{nodeTeaching.definition}</p></section>
      <section><h5>Receives</h5><ul>{#each nodeTeaching.receives as item}<li>{item}</li>{/each}</ul></section>
      <section><h5>Produces</h5><ul>{#each nodeTeaching.produces as item}<li>{item}</li>{/each}</ul></section>
      <section class="wide"><h5>Responsibility</h5><p>{nodeTeaching.responsibility}</p></section>
      <section><h5>Controls and guarantees</h5><ul>{#each nodeTeaching.controls as item}<li>{item}</li>{/each}</ul></section>
      <section class="failure"><h5>Failure behavior</h5><p>{nodeTeaching.failure_behavior}</p></section>
      <section class="why wide"><h5>Why it matters</h5><p>{nodeTeaching.why_it_matters}</p></section>
    </div>
  {:else if edgeTeaching}
    <div class="teaching-grid edge-grid">
      <section class="wide"><h5>What crosses this boundary</h5><p>{edgeTeaching.payload}</p></section>
      <section><h5>What changed</h5><p>{edgeTeaching.transformation}</p></section>
      <section><h5>Trust boundary</h5><p>{edgeTeaching.trust_boundary}</p></section>
      <section><h5>Required before crossing</h5><p>{edgeTeaching.precondition}</p></section>
      <section class="failure"><h5>On failure</h5><p>{edgeTeaching.failure_behavior}</p></section>
      <section class="why wide"><h5>Why this handoff exists</h5><p>{edgeTeaching.why_it_matters}</p></section>
    </div>
  {:else if moduleDetails}
    <section class="module-detail"><h5>Explanation</h5><p>{moduleDetails}</p></section>
  {/if}

  {#if sources.length}<SourceLinks {sources} {sourceCommit} compact />{/if}
</article>

<style>
  .teaching-inspector{border:1px solid var(--cogentrex-border,var(--border));border-radius:.9rem;background:var(--cogentrex-surface,#0a1022);padding:1rem;box-shadow:0 12px 30px rgba(0,0,0,.26)}
  header{border-left:4px solid var(--cogentrex-orange,#f6b44b);padding-left:.85rem}h4{margin:.35rem 0;color:var(--cogentrex-text,#f4f7fb);font-size:1.18rem}.summary{margin:.3rem 0 0;color:var(--cogentrex-text-secondary,#cbd5e1);font-size:.86rem;line-height:1.55}.teaching-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.7rem;margin-top:1rem}.teaching-grid section,.module-detail{border:1px solid #2b3b50;border-radius:.65rem;background:var(--cogentrex-surface-raised,#11182d);padding:.8rem}.teaching-grid .wide{grid-column:1/-1}.teaching-grid .failure{border-color:color-mix(in srgb,var(--cogentrex-coral,#fb7185) 50%,#2b3b50)}.teaching-grid .why{border-color:color-mix(in srgb,var(--cogentrex-orange,#f6b44b) 62%,#2b3b50);box-shadow:0 0 18px var(--cogentrex-orange-glow,rgba(246,180,75,.16))}.teaching-grid h5,.module-detail h5{margin:0 0 .38rem;color:var(--cogentrex-orange,#f6b44b);font-size:.68rem;letter-spacing:.09em;text-transform:uppercase}.teaching-grid p,.module-detail p{margin:0;color:var(--cogentrex-text-secondary,#cbd5e1);font-size:.78rem;line-height:1.58}.teaching-grid ul{display:grid;gap:.3rem;margin:0;padding-left:1.1rem;color:var(--cogentrex-text-secondary,#cbd5e1);font-size:.76rem;line-height:1.5}.module-detail{margin-top:1rem;border-color:color-mix(in srgb,var(--cogentrex-orange,#f6b44b) 58%,#2b3b50)}@media(max-width:620px){.teaching-grid{grid-template-columns:1fr}.teaching-grid .wide{grid-column:auto}}
</style>
