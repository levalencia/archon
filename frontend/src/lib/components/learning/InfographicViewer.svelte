<script lang="ts">
  import {
    ArrowRight,
    BookOpenCheck,
    Code2,
    Eye,
    FlaskConical,
    Globe2,
    Gauge,
    LockKeyhole,
    MonitorCheck,
    RadioTower,
    SearchCheck,
    ShieldCheck,
    TriangleAlert,
  } from 'lucide-svelte';
  import SourceLinks from './SourceLinks.svelte';
  import TeachingInspector from './TeachingInspector.svelte';
  import type { LearningNode, TeachingModule } from '$lib/learning-teaching';
  import type { SourceReference } from '$lib/source-links';

  let { content, sourceCommit }: {
    content: {
      title: string;
      description: string;
      nodes: LearningNode[];
      modules?: TeachingModule[];
      sources?: SourceReference[];
    };
    sourceCommit: string;
  } = $props();

  let selected = $state(0);
  let selectedModuleId = $state('');
  const stageIcons = [Code2, FlaskConical, MonitorCheck, RadioTower, Globe2];
  const proofLabels = ['Implemented', 'Deterministic', 'Observed locally', 'Live provider', 'Publicly deployed'];
  const sectionColors = ['#f59e0b', '#22c55e', '#3b82f6', '#a78bfa', '#fb7185'];
  const rules = [
    { id: 'evidence-before-confidence', title: 'Evidence before confidence', text: 'A claim is only as strong as the observation behind it.', icon: SearchCheck },
    { id: 'bound-the-environment', title: 'Bound the environment', text: 'Tests, local runtime, live provider, and public deployment are different proof scopes.', icon: LockKeyhole },
    { id: 'expose-limitations', title: 'Expose limitations', text: 'State what remains unverified instead of letting presentation quality imply proof.', icon: Eye },
  ];
  const impacts = [
    { id: 'credibility', title: 'Credibility', text: 'Demos say exactly what the evidence supports.' },
    { id: 'debuggability', title: 'Debuggability', text: 'Failures point to a specific proof boundary.' },
    { id: 'safer-iteration', title: 'Safer iteration', text: 'New capability does not silently inherit stronger claims.' },
    { id: 'interview-clarity', title: 'Interview clarity', text: 'Trade-offs remain explainable under scrutiny.' },
  ];

  let selectedModule = $derived(content.modules?.find((module) => module.id === selectedModuleId));

  function selectModule(id: string) {
    selectedModuleId = id;
    selected = -1;
  }

  function selectLevel(index: number) {
    selected = index;
    selectedModuleId = '';
  }
</script>

<article class="infographic" aria-labelledby="infographic-title">
  <header class="hero">
    <div>
      <span class="kicker">Archon evidence engineering</span>
      <h3 id="infographic-title">{content.title}</h3>
      <p>{content.description}</p>
    </div>
    <div class="hero-mark" aria-hidden="true">
      <Gauge size={34}/><strong>5 LEVELS</strong><span>evidence standard</span>
    </div>
  </header>

  <div class="editorial-grid">
    <section class="module principles" aria-labelledby="principles-title">
      <div class="module-title amber"><ShieldCheck size={18}/><h4 id="principles-title">Core principles</h4></div>
      <div class="module-body">
        {#each rules as rule}
          {@const Icon = rule.icon}
          <button class="rule interactive" class:active={selectedModuleId === rule.id} onclick={() => selectModule(rule.id)} aria-pressed={selectedModuleId === rule.id}>
            <Icon size={22}/><span><strong>{rule.title}</strong><small>{rule.text}</small></span>
          </button>
        {/each}
      </div>
    </section>

    <section class="module architecture" aria-labelledby="architecture-title">
      <div class="module-title green"><BookOpenCheck size={18}/><h4 id="architecture-title">Evidence architecture</h4></div>
      <div class="architecture-body">
        <button class="claim-box interactive" class:active={selectedModuleId === 'capability-claim'} onclick={() => selectModule('capability-claim')} aria-pressed={selectedModuleId === 'capability-claim'}><span>Capability claim</span><strong>What are we saying Archon can do?</strong></button>
        <ArrowRight class="flow-arrow" size={28}/>
        <div class="proof-stack">
          <button class="interactive" class:active={selectedModuleId === 'code-proof'} onclick={() => selectModule('code-proof')} aria-pressed={selectedModuleId === 'code-proof'}><span>Code</span><small>implementation exists</small></button>
          <button class="interactive" class:active={selectedModuleId === 'test-proof'} onclick={() => selectModule('test-proof')} aria-pressed={selectedModuleId === 'test-proof'}><span>Tests</span><small>behavior is deterministic</small></button>
          <button class="interactive" class:active={selectedModuleId === 'observation-proof'} onclick={() => selectModule('observation-proof')} aria-pressed={selectedModuleId === 'observation-proof'}><span>Observation</span><small>runtime evidence exists</small></button>
        </div>
        <ArrowRight class="flow-arrow" size={28}/>
        <button class="verdict-box interactive" class:active={selectedModuleId === 'qualified-verdict'} onclick={() => selectModule('qualified-verdict')} aria-pressed={selectedModuleId === 'qualified-verdict'}><span>Qualified verdict</span><strong>Proven only within the observed boundary</strong></button>
      </div>
      <div class="cross-cutting"><Eye size={18}/><span>Provenance, limitations, and source links apply across every level.</span></div>
    </section>

    <section class="module journey" aria-labelledby="journey-title">
      <div class="module-title blue"><RadioTower size={18}/><h4 id="journey-title">How confidence grows</h4></div>
      <div class="journey-track" aria-label="Five ordered evidence levels">
        {#each content.nodes as node, index}
          {@const Icon = stageIcons[index] ?? Code2}
          <button class:active={selected === index} style={`--level-color:${sectionColors[index] ?? '#f59e0b'}`} onclick={() => selectLevel(index)} aria-pressed={selected === index}>
            <span class="step">{index + 1}</span><Icon size={22}/><strong>{node.label}</strong><small>{proofLabels[index] ?? 'Additional proof'}</small>
          </button>
          {#if index < content.nodes.length - 1}<ArrowRight class="journey-arrow" size={20}/>{/if}
        {/each}
      </div>
      {#if selectedModule}
        <div class="infographic-inspector"><TeachingInspector eyebrow={`${selectedModule.category} explanation`} title={selectedModule.label} summary={selectedModule.summary} moduleDetails={selectedModule.details} sources={selectedModule.sources} {sourceCommit}/></div>
      {:else if selected >= 0 && content.nodes[selected]}
        <div class="infographic-inspector"><TeachingInspector eyebrow={`Level ${selected + 1} · ${proofLabels[selected]}`} title={content.nodes[selected].label} summary={content.nodes[selected].summary} nodeTeaching={content.nodes[selected].teaching} moduleDetails={content.nodes[selected].details} sources={content.nodes[selected].sources} {sourceCommit}/></div>
      {/if}
    </section>

    <section class="module why" aria-labelledby="why-title">
      <div class="module-title purple"><Gauge size={18}/><h4 id="why-title">Why this matters</h4></div>
      <div class="impact-grid">
        {#each impacts as impact}
          <button class="interactive" class:active={selectedModuleId === impact.id} onclick={() => selectModule(impact.id)} aria-pressed={selectedModuleId === impact.id}><strong>{impact.title}</strong><p>{impact.text}</p></button>
        {/each}
      </div>
    </section>

    <section class="module checklist" aria-labelledby="checklist-title">
      <div class="module-title coral"><TriangleAlert size={18}/><h4 id="checklist-title">Claim review checklist</h4></div>
      <ul><li><span>01</span>What executed?</li><li><span>02</span>Where did it execute?</li><li><span>03</span>Was the provider real or mocked?</li><li><span>04</span>What failure remains possible?</li><li><span>05</span>Can another reviewer reproduce it?</li></ul>
    </section>
  </div>

  <div class="principle"><TriangleAlert size={22}/><div><span>Non-negotiable</span><strong>A timeout is not PASS. A mock is not live evidence. A manifest is not deployment.</strong></div></div>
  {#if content.sources?.length}<SourceLinks sources={content.sources} {sourceCommit} heading="Evidence sources" />{/if}
</article>

<style>
  .infographic{border:1px solid var(--archon-border,var(--border));border-radius:1rem;padding:clamp(1rem,2.5vw,1.75rem);background:var(--archon-canvas,#050b16);color:var(--archon-text,#f8fafc)}
  .hero{display:flex;justify-content:space-between;gap:1.5rem;align-items:center;padding:1rem 1.15rem 1.25rem;border-bottom:5px solid var(--archon-orange,#f59e0b);background:var(--archon-surface,#0f172a);border-radius:.8rem .8rem .25rem .25rem}
  .kicker{color:var(--archon-orange,#f59e0b);font:800 .68rem var(--font-mono);letter-spacing:.14em;text-transform:uppercase}.hero h3{margin:.35rem 0;font-size:clamp(1.8rem,4vw,3.2rem);line-height:1;color:#f8fafc}.hero p{margin:.55rem 0 0;max-width:760px;color:#cbd5e1;line-height:1.55}.hero-mark{display:grid;place-items:center;min-width:125px;padding:.8rem;border:2px solid var(--archon-orange,#f59e0b);border-radius:.75rem;color:#f59e0b;box-shadow:0 0 24px var(--archon-orange-glow,rgba(245,158,11,.22))}.hero-mark strong{font-size:1rem;letter-spacing:.12em}.hero-mark span{font-size:.68rem;color:#94a3b8}
  .editorial-grid{display:grid;grid-template-columns:minmax(220px,.72fr) minmax(0,1.6fr);gap:.85rem;margin-top:.85rem}.module{overflow:hidden;border:1px solid #334155;border-radius:.75rem;background:#0f172a;box-shadow:0 8px 24px rgba(0,0,0,.28)}.module-title{display:flex;align-items:center;gap:.5rem;padding:.65rem .8rem;color:white}.module-title h4{margin:0;font-size:.82rem;letter-spacing:.05em;text-transform:uppercase}.amber{background:#d97706}.green{background:#15803d}.blue{background:#2563eb}.purple{background:#7c3aed}.coral{background:#e11d48}
  .module-body{display:grid;gap:.35rem;padding:.7rem}.interactive{font:inherit;color:inherit;cursor:pointer;text-align:left;transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease}.interactive:focus-visible{outline:2px solid var(--archon-orange,#f59e0b);outline-offset:2px}.interactive:focus-visible,.interactive.active{border-color:var(--archon-orange,#f59e0b)!important;box-shadow:0 0 0 1px rgba(245,158,11,.45),0 0 24px var(--archon-orange-glow,rgba(245,158,11,.22))!important}.rule{display:grid;width:100%;grid-template-columns:30px 1fr;gap:.55rem;padding:.6rem;border:0;border-bottom:1px solid #263449;background:transparent;color:#e2e8f0}.rule:last-child{border-bottom:0}.rule :global(svg){color:#f59e0b}.rule span{display:block}.rule strong,.impact-grid strong{font-size:.76rem;text-transform:uppercase}.rule small{display:block;margin-top:.15rem;color:#aebdd0;font-size:.7rem;line-height:1.45}
  .architecture-body{display:grid;grid-template-columns:1fr auto 1.05fr auto 1fr;align-items:center;gap:.65rem;padding:1rem}.claim-box,.verdict-box{min-height:105px;display:flex;flex-direction:column;justify-content:center;padding:.8rem;border-radius:.65rem;color:#f8fafc}.claim-box{border:2px solid #60a5fa;background:#0b2447}.verdict-box{border:2px solid #4ade80;background:#0b2d24}.claim-box span,.verdict-box span{font:800 .62rem var(--font-mono);text-transform:uppercase;color:#b8c5d6}.claim-box strong,.verdict-box strong{margin-top:.35rem;font-size:.8rem;line-height:1.35}.proof-stack{display:grid;gap:.35rem}.proof-stack button{display:block;width:100%;padding:.45rem .55rem;border:1px solid #2d7d54;border-radius:.4rem;background:#0b2d24;text-align:left}.proof-stack span{display:block;color:#86efac;font-size:.72rem;font-weight:800}.proof-stack small{color:#b7c7d8;font-size:.6rem}.architecture-body :global(.flow-arrow){color:#22c55e}.cross-cutting{display:flex;justify-content:center;align-items:center;gap:.5rem;margin:0 .8rem .8rem;padding:.55rem;border:1px dashed #4ade80;border-radius:.45rem;background:#0b2d24;color:#bbf7d0;font-size:.68rem;font-weight:700}
  .journey{grid-column:1/-1}.journey-track{display:flex;align-items:center;justify-content:center;gap:.35rem;padding:1rem}.journey-track button{position:relative;flex:1;min-width:0;min-height:115px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.35rem;border:2px solid color-mix(in srgb,var(--level-color) 70%,#334155);border-radius:.65rem;background:color-mix(in srgb,var(--level-color) 14%,#0f172a);color:#f8fafc;padding:.65rem;text-align:center}.journey-track button.active,.journey-track button:hover,.journey-track button:focus-visible{border-color:var(--level-color);box-shadow:0 0 0 3px color-mix(in srgb,var(--level-color) 20%,transparent);transform:translateY(-2px)}.journey-track button :global(svg){color:var(--level-color)}.journey-track strong{font-size:.72rem;line-height:1.25}.journey-track small{color:#b8c5d6;font-size:.61rem}.step{position:absolute;top:-9px;left:-9px;display:grid;place-items:center;width:23px;height:23px;border-radius:50%;background:var(--level-color);color:white;font:800 .65rem var(--font-mono)}.journey-track :global(.journey-arrow){flex:0 0 auto;color:#64748b}.infographic-inspector{margin:0 1rem 1rem}
  .why,.checklist{min-height:225px}.impact-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;padding:.8rem}.impact-grid button{padding:.65rem;border:0;border-left:3px solid #a78bfa;background:#111c2e;color:#f8fafc;text-align:left}.impact-grid p{margin:.15rem 0 0;color:#aebdd0;font-size:.7rem;line-height:1.45}.checklist ul{display:grid;gap:.3rem;list-style:none;margin:0;padding:.8rem}.checklist li{display:flex;align-items:center;gap:.55rem;padding:.45rem;border-bottom:1px solid #263449;font-size:.72rem;font-weight:700;color:#e2e8f0}.checklist li:last-child{border:0}.checklist li span{color:#fb7185;font:800 .63rem var(--font-mono)}
  .principle{display:flex;align-items:center;gap:.75rem;margin-top:.85rem;padding:.8rem 1rem;border-radius:.65rem;background:#172033;color:#fff}.principle :global(svg){flex:none;color:#f59e0b}.principle span{display:block;color:#fbbf24;font:800 .62rem var(--font-mono);text-transform:uppercase}.principle strong{font-size:.78rem;line-height:1.45}
  @media(max-width:900px){.editorial-grid{grid-template-columns:1fr}.journey{grid-column:auto}.architecture-body{grid-template-columns:1fr}.architecture-body :global(.flow-arrow){transform:rotate(90deg);justify-self:center}.journey-track{align-items:stretch;overflow-x:auto;justify-content:flex-start}.journey-track button{min-width:135px}.why,.checklist{min-height:0}}
  @media(max-width:560px){.hero{align-items:flex-start}.hero-mark{display:none}.impact-grid{grid-template-columns:1fr}.journey-track :global(.journey-arrow){display:none}}
  @media(forced-colors:active){.interactive:focus-visible{outline:2px solid CanvasText}.interactive.active{border-color:Highlight!important}}
</style>
