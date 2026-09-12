<script lang="ts">
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';

  type KeyTerm = { term: string; definition: string };
  type Slide = {
    id: string;
    title: string;
    message: string;
    visual: string;
    notes?: string;
    presenter_script?: string;
    key_terms?: KeyTerm[];
    common_misconception?: string;
    transition?: string;
    sources: SourceReference[];
  };
  let { content, sourceCommit }: { content: { slides: Slide[] }; sourceCommit: string } = $props();
  let index = $state(0);
  let notesOpen = $state(false);
  let slide = $derived(content.slides[index]);

  function move(next: number) {
    index = Math.max(0, Math.min(content.slides.length - 1, next));
  }

</script>

<section class="deck" aria-label="Slide presentation">
  <div class="slide-count" aria-live="polite">Slide {index + 1} of {content.slides.length}</div>
  <article role="group" aria-roledescription="slide" aria-label={`Slide ${index + 1} of ${content.slides.length}`}>
    <span class="eyebrow">Cogentrex request lifecycle</span>
    <h3>{slide.title}</h3>
    <p class="message">{slide.message}</p>
    <div class="visual" aria-label={`${slide.visual.replaceAll('-', ' ')} visual`}>
      <span>{slide.visual.replaceAll('-', ' ')}</span>
    </div>
  </article>
  <div class="controls">
    <button onclick={() => move(index - 1)} disabled={index === 0} aria-label="Previous slide">← Previous</button>
    <div class="dots" aria-label="Slide position">
      {#each content.slides as _, dot}<button class:active={dot === index} onclick={() => move(dot)} aria-label={`Go to slide ${dot + 1}`} aria-current={dot === index ? 'step' : undefined}></button>{/each}
    </div>
    <button onclick={() => move(index + 1)} disabled={index === content.slides.length - 1} aria-label="Next slide">Next →</button>
  </div>
  <button class="notes-toggle" onclick={() => notesOpen = !notesOpen} aria-expanded={notesOpen}>Teach this slide</button>
  {#if notesOpen}
    <aside class="notes" aria-label={`Teaching script for ${slide.title}`}>
      <span class="notes-label">Presenter script</span>
      <p class="script">{slide.presenter_script ?? slide.notes}</p>
      {#if slide.key_terms?.length}
        <div class="terms"><h4>Key terms</h4><dl>{#each slide.key_terms as item}<div><dt>{item.term}</dt><dd>{item.definition}</dd></div>{/each}</dl></div>
      {/if}
      {#if slide.common_misconception}<div class="misconception"><strong>Common misconception</strong><p>{slide.common_misconception}</p></div>{/if}
      {#if slide.transition}<div class="transition"><strong>Transition</strong><p>{slide.transition}</p></div>{/if}
      <SourceLinks sources={slide.sources} {sourceCommit} heading="Read the supporting documentation" />
    </aside>
  {/if}
</section>

<style>
  .deck{outline:none;border:1px solid var(--border);border-radius:1rem;background:radial-gradient(circle at 80% 0,var(--cogentrex-orange-glow),transparent 35%),var(--cogentrex-canvas,#050712);padding:clamp(1rem,3vw,2.5rem);min-height:560px;display:flex;flex-direction:column}.slide-count{align-self:flex-end;color:var(--muted);font:700 .7rem var(--font-mono)}article{display:grid;grid-template-rows:auto auto auto 1fr;gap:1rem;flex:1}h3{font-size:clamp(1.8rem,4vw,3.5rem);line-height:1.05;max-width:18ch;margin:.5rem 0}.message{font-size:clamp(1rem,2vw,1.35rem);line-height:1.55;color:var(--secondary);max-width:70ch}.visual{min-height:230px;border:1px solid var(--border);border-radius:1rem;display:grid;place-items:center;background:linear-gradient(135deg,rgba(127,167,255,.08),rgba(85,214,190,.06));padding:2rem}.visual span{text-transform:uppercase;text-align:center;color:var(--accent);font:800 clamp(1.5rem,5vw,4rem) var(--font-mono)}.controls{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-top:1rem}.controls button,.notes-toggle{min-height:42px;border:1px solid var(--border);border-radius:.65rem;background:var(--panel);color:var(--text);padding:.6rem .8rem}.dots{display:flex;gap:.35rem;flex-wrap:wrap;justify-content:center}.dots button{width:10px;height:10px;min-height:10px;padding:0;border-radius:50%;background:var(--muted)}.dots button.active{background:var(--accent)}.notes-toggle{margin-top:1rem;width:max-content;border-color:var(--accent);color:var(--accent);font-weight:700}.notes{margin-top:.75rem;border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:.75rem;padding:1rem 1.1rem;background:rgba(2,6,23,.5)}.notes-label{color:var(--accent);font:700 .68rem var(--font-mono);letter-spacing:.1em;text-transform:uppercase}.script{color:var(--secondary);font-size:.9rem;line-height:1.75;max-width:80ch}.terms h4{margin:.8rem 0 .45rem;font-size:.8rem}.terms dl{display:grid;gap:.45rem;margin:0}.terms dl div{display:grid;grid-template-columns:minmax(110px,.25fr) 1fr;gap:.75rem}.terms dt{color:var(--text);font-weight:700}.terms dd{margin:0;color:var(--secondary)}.misconception,.transition{margin-top:.8rem;border-radius:.55rem;padding:.75rem;background:rgba(240,189,98,.07);color:var(--secondary)}.transition{background:rgba(127,167,255,.07)}.misconception strong,.transition strong{display:block;margin-bottom:.25rem;color:var(--warning);font-size:.72rem;text-transform:uppercase}.transition strong{color:#7fa7ff}.misconception p,.transition p{margin:0;line-height:1.55}@media(max-width:640px){.terms dl div{grid-template-columns:1fr}.controls{align-items:flex-end}.dots{max-width:150px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
  .visual{background:linear-gradient(135deg,color-mix(in srgb,var(--cogentrex-blue) 9%,transparent),var(--cogentrex-orange-glow));box-shadow:inset 0 0 32px rgba(5,11,22,.45)}
  .dots button.active,.notes-toggle{box-shadow:0 0 14px var(--cogentrex-orange-glow)}
</style>
