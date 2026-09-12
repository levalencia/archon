<script lang="ts">
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import { ExternalLink, MessageCircleQuestion, Send, X } from 'lucide-svelte';
  import {
    askLearningTutor,
    citationHref,
    getLearningTutorSession,
    streamLearningTutor,
    type LearningTutorAnswer,
    type LearningTutorContext,
  } from '$lib/learning-tutor';
  import TutorDiagram from './TutorDiagram.svelte';

  let {
    context,
    contextTitle,
  }: {
    context: LearningTutorContext;
    contextTitle: string;
  } = $props();

  let open = $state(false);
  let question = $state('');
  let loading = $state(false);
  let error = $state('');
  let progressMessage = $state('');
  let streamingText = $state('');
  let answers = $state<Array<{ question: string; result: LearningTutorAnswer }>>([]);
  let restoredKey = $state('');

  function key(value: LearningTutorContext): string {
    if (value.artifact_id) return `artifact:${value.artifact_id}`;
    if (value.concept_id) return `concept:${value.concept_id}`;
    if (value.module_id) return `module:${value.module_id}`;
    if (value.story_id) return `story:${value.story_id}:step:${value.step_index ?? 0}`;
    return `view:${value.view}`;
  }

  function markdown(value: string): string {
    return DOMPurify.sanitize(marked.parse(value, { async: false }) as string, {
      USE_PROFILES: { html: true },
    });
  }

  async function restore() {
    if (typeof localStorage === 'undefined') return;
    const currentKey = key(context);
    if (restoredKey === currentKey) return;
    restoredKey = currentKey;
    const sessionId = localStorage.getItem(`cogentrex_learning_tutor:${currentKey}`);
    if (!sessionId) { answers = []; return; }
    try {
      const session = await getLearningTutorSession(sessionId);
      answers = session.turns.map(turn => ({
        question: turn.question,
        result: {
          run_id: '', session_id: session.id, answer_markdown: turn.answer_markdown,
          citations: turn.citations, related_questions: [], diagram: turn.diagram,
          grounded: Boolean(turn.metrics.grounded ?? true), unsupported: [], metrics: turn.metrics,
        },
      }));
    } catch {
      localStorage.removeItem(`cogentrex_learning_tutor:${key(context)}`);
      answers = [];
      error = 'The previous tutor session could not be restored.';
    }
  }

  async function submit(value = question) {
    const clean = value.trim();
    if (!clean || loading) return;
    loading = true;
    error = '';
    progressMessage = '';
    streamingText = '';
    try {
      await streamLearningTutor(clean, context, {
        onStatus(data) {
          progressMessage = data.message;
        },
        onProgress(data) {
          progressMessage = data.message;
        },
        onAnswerDelta(data) {
          streamingText += data.delta;
        },
        onResult(data) {
          answers = [...answers, { question: clean, result: data }];
          streamingText = '';
          progressMessage = '';
          question = '';
          if (typeof localStorage !== 'undefined') {
            localStorage.setItem(`cogentrex_learning_tutor:${key(context)}`, data.session_id);
          }
        },
        onError(data) {
          error = data.message;
        },
        onDone() {
          loading = false;
        },
      });
    } catch (cause) {
      error = cause instanceof Error ? cause.message : 'The learning tutor is unavailable.';
    } finally {
      loading = false;
      progressMessage = '';
    }
  }

  $effect(() => {
    const currentKey = key(context);
    if (currentKey !== restoredKey) restoredKey = '';
    if (open) void restore();
  });
</script>

<button class="tutor-trigger" aria-label="Ask about this topic" onclick={() => { open = true; void restore(); }}>
  <MessageCircleQuestion size={20}/><span>Ask about this topic</span>
</button>

{#if open}
  <div class="backdrop" role="presentation" onclick={(event) => { if (event.currentTarget === event.target) open = false; }}>
    <aside class="panel" aria-label="Learning tutor">
      <header>
        <div><span class="eyebrow">Context-aware tutor</span><h2>Ask about this topic</h2><p>{contextTitle}{#if context.playback_seconds !== undefined} · {Math.floor(context.playback_seconds / 60)}:{String(Math.floor(context.playback_seconds % 60)).padStart(2, '0')}{/if}</p></div>
        <button class="icon" aria-label="Close learning tutor" onclick={() => open = false}><X size={18}/></button>
      </header>
      <div class="thread" aria-live="polite">
        {#if !answers.length}
          <div class="empty"><MessageCircleQuestion size={28}/><strong>Ask from the page you are viewing</strong><p>The answer will prioritize this topic and cite documentation, code, tests, and video timestamps.</p></div>
        {/if}
        {#each answers as turn}
          <article class="question"><strong>You</strong><p>{turn.question}</p></article>
          <article class="answer"><strong>Cogentrex tutor</strong><div class="markdown">{@html markdown(turn.result.answer_markdown)}</div>
            {#if turn.result.diagram}<TutorDiagram diagram={turn.result.diagram}/>{/if}
            {#if turn.result.citations.length}
              <section class="citations" aria-label="Tutor citations"><h3>Evidence · {turn.result.citations.length}</h3>
                {#each turn.result.citations as citation}
                  {@const href = citationHref(citation)}
                  <article><div><span>{citation.id}</span><strong>{citation.title}</strong></div><p>{citation.excerpt}</p>{#if href}<a href={href} target={href.startsWith('http') ? '_blank' : undefined} rel={href.startsWith('http') ? 'noopener noreferrer' : undefined}>Open evidence <ExternalLink size={12}/></a>{/if}</article>
                {/each}
              </section>
            {/if}
            {#if turn.result.related_questions.length}<div class="related"><span>Continue learning</span>{#each turn.result.related_questions as item}<button onclick={() => submit(item)}>{item}</button>{/each}</div>{/if}
          </article>
        {/each}
        {#if loading}<p class="loading" role="status">{progressMessage || 'Retrieving and verifying evidence…'}</p>{/if}
        {#if streamingText}<article class="answer streaming"><strong>Cogentrex tutor</strong><div class="markdown">{@html markdown(streamingText)}</div></article>{/if}
        {#if error}<p class="error" role="alert">{error}</p>{/if}
      </div>
      <form onsubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label for="learning-tutor-question">Question about this topic</label>
        <textarea id="learning-tutor-question" bind:value={question} maxlength="5000" rows="3" placeholder="For example: What is a service slot?"></textarea>
        <button type="submit" disabled={loading || !question.trim()} aria-label="Ask Cogentrex tutor"><Send size={16}/>Ask</button>
      </form>
    </aside>
  </div>
{/if}
<svelte:window onkeydown={(event) => { if (open && event.key === 'Escape') open = false; }}/>

<style>
  .tutor-trigger{position:fixed;right:1rem;bottom:1rem;z-index:45;display:flex;min-height:44px;align-items:center;gap:.5rem;border:1px solid var(--accent);border-radius:999px;background:var(--accent);color:#111;padding:.65rem 1rem;font-weight:800;box-shadow:0 8px 30px rgba(0,0,0,.35)}
  .backdrop{position:fixed;inset:0;z-index:60;background:rgba(0,0,0,.38)}
  .panel{position:absolute;inset:0 0 0 auto;display:grid;width:min(430px,100vw);grid-template-rows:auto minmax(0,1fr) auto;border-left:1px solid var(--border);background:var(--bg);box-shadow:-16px 0 45px rgba(0,0,0,.45)}
  header{display:flex;align-items:flex-start;justify-content:space-between;gap:1rem;border-bottom:1px solid var(--border);padding:1rem}header h2{margin:.3rem 0 0;font-size:1.2rem}header p{margin:.35rem 0 0;color:var(--muted);font-size:.75rem}.icon{display:grid;min-height:44px;min-width:44px;place-items:center;border:1px solid var(--border);border-radius:.65rem;color:var(--text)}
  .thread{overflow:auto;padding:1rem}.empty{display:grid;justify-items:center;gap:.55rem;border:1px dashed var(--border);border-radius:.8rem;padding:1.25rem;text-align:center;color:var(--muted)}.empty strong{color:var(--text)}.empty p{margin:0;font-size:.8rem;line-height:1.55}.question,.answer{margin-bottom:1rem;border-radius:.85rem;padding:.85rem}.question{margin-left:2rem;background:var(--accent-glow);border:1px solid color-mix(in srgb,var(--accent) 50%,var(--border))}.answer{border:1px solid var(--border);background:var(--panel)}.question>strong,.answer>strong{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}.question p{margin:.4rem 0 0}.markdown{font-size:.86rem;line-height:1.65}.markdown :global(pre){overflow:auto;border:1px solid var(--border);border-radius:.6rem;background:#05080d;padding:.75rem}.markdown :global(code){font-family:var(--font-mono)}
  .citations{margin-top:1rem;border-top:1px solid var(--border);padding-top:.75rem}.citations h3{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.citations article{margin-top:.6rem;border:1px solid var(--border);border-radius:.65rem;padding:.7rem}.citations article div{display:flex;gap:.5rem}.citations article span{color:var(--accent);font-family:var(--font-mono);font-weight:800}.citations article p{display:-webkit-box;overflow:hidden;margin:.45rem 0;color:var(--secondary);font-size:.75rem;line-height:1.45;-webkit-box-orient:vertical;-webkit-line-clamp:3;line-clamp:3}.citations a{display:inline-flex;align-items:center;gap:.3rem;color:var(--accent);font-size:.72rem}.related{display:grid;gap:.4rem;margin-top:.8rem}.related>span{font-size:.68rem;text-transform:uppercase;color:var(--muted)}.related button{min-height:40px;border:1px solid var(--border);border-radius:.55rem;padding:.5rem;text-align:left;color:var(--secondary)}
  form{display:grid;gap:.55rem;border-top:1px solid var(--border);background:var(--panel);padding:1rem}form label{font-size:.72rem;font-weight:700;color:var(--secondary)}textarea{resize:vertical;border:1px solid var(--border);border-radius:.65rem;background:var(--bg);color:var(--text);padding:.7rem;line-height:1.5}form button{display:flex;min-height:44px;align-items:center;justify-content:center;gap:.4rem;border-radius:.65rem;background:var(--accent);color:#111;font-weight:800}form button:disabled{opacity:.5}.loading,.error{border-radius:.65rem;padding:.7rem;font-size:.8rem}.loading{background:var(--accent-glow);color:var(--accent)}.error{background:rgba(255,107,114,.08);color:var(--danger)}
  @media(max-width:720px){.tutor-trigger{bottom:5rem}.panel{width:100vw}}
</style>
