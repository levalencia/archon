<script lang="ts">
  import { onMount, tick } from 'svelte';
  import * as d3 from 'd3';
  import {
    BookOpen,
    Check,
    ChevronLeft,
    ChevronRight,
    ExternalLink,
    Focus,
    GitBranch,
    RotateCcw,
    Search,
    Sparkles,
  } from 'lucide-svelte';
  import {
    STATUS_META,
    filterLearningNodes,
    loadLearningGraph,
    relatedConceptIds,
    type ConceptStatus,
    type LearningGraph,
    type LearningLink,
    type LearningNode,
    type LearningTour,
  } from '$lib/visual-learning';

  interface SimNode extends LearningNode, d3.SimulationNodeDatum {}
  interface SimLink extends d3.SimulationLinkDatum<SimNode> {
    source: string | SimNode;
    target: string | SimNode;
    kinds: string[];
    labels: string[];
  }

  interface DetailSection {
    heading: string;
    links: LearningLink[];
  }

  let graph = $state<LearningGraph | null>(null);
  let loading = $state(true);
  let error = $state('');
  let query = $state('');
  let statusFilter = $state<ConceptStatus | 'all'>('all');
  let moduleFilter = $state('');
  let selectedId = $state('');
  let activeTourId = $state('');
  let tourStep = $state(0);
  let visited = $state<Set<string>>(new Set());
  let svgElement = $state<SVGSVGElement | null>(null);
  let simulation: d3.Simulation<SimNode, SimLink> | null = null;
  let nodeSelection: d3.Selection<SVGGElement, SimNode, SVGGElement, unknown> | null = null;
  let linkSelection: d3.Selection<SVGLineElement, SimLink, SVGGElement, unknown> | null = null;
  let zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null;

  const width = 1200;
  const height = 760;

  let selectedNode: LearningNode | null = $derived.by(() => {
    const current = graph;
    return current?.nodes.find((node: LearningNode) => node.id === selectedId) ?? null;
  });
  let activeTour: LearningTour | null = $derived.by(() => {
    const current = graph;
    return current?.tours.find((tour: LearningTour) => tour.id === activeTourId) ?? null;
  });
  let visibleNodes: LearningNode[] = $derived.by(() => {
    const current = graph;
    return current
      ? filterLearningNodes(current.nodes, {
          query,
          status: statusFilter,
          moduleId: moduleFilter,
        })
      : [];
  });
  let currentTourNodeId = $derived(activeTour?.concept_ids[tourStep] ?? '');
  let detailSections: DetailSection[] = $derived.by(() => selectedNode ? [
    { heading: 'Source code', links: selectedNode.sources },
    { heading: 'Tests', links: selectedNode.tests },
    { heading: 'Evidence', links: selectedNode.evidence },
  ] : []);

  function nodeId(value: string | SimNode): string {
    return typeof value === 'string' ? value : value.id;
  }

  function shortLabel(value: string): string {
    return value.length > 24 ? `${value.slice(0, 22)}…` : value;
  }

  function markVisited(id: string) {
    const next = new Set(visited);
    next.add(id);
    visited = next;
    localStorage.setItem('archon.visual-learning.visited', JSON.stringify([...next]));
  }

  function selectNode(id: string) {
    const currentTour = graph?.tours.find(tour => tour.id === activeTourId);
    if (currentTour) {
      const step = currentTour.concept_ids.indexOf(id);
      if (step >= 0) tourStep = step;
      else clearTour();
    }
    selectedId = id;
    markVisited(id);
  }

  function startTour(id: string) {
    const tour = graph?.tours.find(item => item.id === id);
    if (!tour) return;
    activeTourId = id;
    tourStep = 0;
    selectNode(tour.concept_ids[0]);
  }

  function moveTour(delta: number) {
    if (!activeTour) return;
    tourStep = Math.max(0, Math.min(activeTour.concept_ids.length - 1, tourStep + delta));
    selectNode(activeTour.concept_ids[tourStep]);
  }

  function clearTour() {
    activeTourId = '';
    tourStep = 0;
  }

  function resetFilters() {
    query = '';
    statusFilter = 'all';
    moduleFilter = '';
    clearTour();
  }

  function resetProgress() {
    visited = new Set();
    localStorage.removeItem('archon.visual-learning.visited');
  }

  function zoomBy(factor: number) {
    if (!zoomBehavior || !svgElement) return;
    d3.select(svgElement).transition().duration(220).call(zoomBehavior.scaleBy, factor);
  }

  function resetView() {
    if (!zoomBehavior || !svgElement) return;
    d3.select(svgElement).transition().duration(260).call(zoomBehavior.transform, d3.zoomIdentity);
  }

  function updateGraphStyles() {
    if (!graph || !nodeSelection || !linkSelection) return;
    const visible = new Set(visibleNodes.map(node => node.id));
    const related = selectedId ? relatedConceptIds(graph, selectedId) : new Set<string>();
    const tourIds = new Set(activeTour?.concept_ids ?? []);
    const interactive = (node: LearningNode) => visible.has(node.id) && (!activeTour || tourIds.has(node.id));

    nodeSelection
      .attr('tabindex', node => interactive(node) ? 0 : -1)
      .attr('aria-hidden', node => interactive(node) ? null : 'true')
      .style('pointer-events', node => interactive(node) ? 'auto' : 'none')
      .attr('opacity', node => {
        if (!visible.has(node.id)) return 0.08;
        if (activeTour && !tourIds.has(node.id)) return 0.16;
        return 1;
      })
      .classed('is-selected', node => node.id === selectedId)
      .classed('is-related', node => related.has(node.id) && node.id !== selectedId)
      .classed('is-visited', node => visited.has(node.id));

    nodeSelection.select<SVGCircleElement>('circle')
      .attr('r', node => node.id === selectedId ? 15 : currentTourNodeId === node.id ? 14 : 10)
      .attr('stroke', node => node.id === selectedId ? '#f8fafc' : related.has(node.id) ? '#55d6be' : '#0f172a')
      .attr('stroke-width', node => node.id === selectedId ? 3 : related.has(node.id) ? 2 : 1.5);

    linkSelection
      .attr('stroke', link => {
        const inTour = tourIds.has(nodeId(link.source)) && tourIds.has(nodeId(link.target));
        return activeTour && inTour ? '#f0bd62' : '#334155';
      })
      .attr('stroke-width', link => {
        const inTour = tourIds.has(nodeId(link.source)) && tourIds.has(nodeId(link.target));
        return activeTour && inTour ? 2.8 : 1.15;
      })
      .attr('opacity', link => {
        const bothVisible = visible.has(nodeId(link.source)) && visible.has(nodeId(link.target));
        if (!bothVisible) return 0.04;
        const inTour = tourIds.has(nodeId(link.source)) && tourIds.has(nodeId(link.target));
        return activeTour ? (inTour ? 0.9 : 0.08) : 0.42;
      });
  }

  function initializeGraph() {
    if (!graph || !svgElement) return;
    simulation?.stop();
    const svg = d3.select(svgElement);
    svg.selectAll('*').remove();

    const viewport = svg.append('g').attr('class', 'graph-viewport');
    zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.35, 3.5])
      .on('zoom', event => viewport.attr('transform', event.transform));
    svg.call(zoomBehavior).on('dblclick.zoom', null);

    const modulePosition = new Map(
      graph.modules.map((module, index) => {
        const angle = (index / graph!.modules.length) * Math.PI * 2 - Math.PI / 2;
        const radius = index % 2 === 0 ? 255 : 320;
        return [module.id, {
          x: width / 2 + Math.cos(angle) * radius,
          y: height / 2 + Math.sin(angle) * radius * 0.72,
        }];
      }),
    );

    const nodes: SimNode[] = graph.nodes.map(node => ({ ...node }));
    const links: SimLink[] = graph.edges.map(edge => ({ ...edge }));

    linkSelection = viewport.append('g')
      .attr('aria-hidden', 'true')
      .selectAll<SVGLineElement, SimLink>('line')
      .data(links)
      .join('line')
      .attr('class', 'concept-link');

    nodeSelection = viewport.append('g')
      .selectAll<SVGGElement, SimNode>('g')
      .data(nodes, node => node.id)
      .join('g')
      .attr('class', 'concept-node')
      .attr('role', 'button')
      .attr('tabindex', 0)
      .attr('aria-label', node => `${node.title}, ${STATUS_META[node.status].label}`)
      .on('click', (_event, node) => selectNode(node.id))
      .on('keydown', (event: KeyboardEvent, node) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectNode(node.id);
        }
      });

    nodeSelection.append('circle')
      .attr('r', 10)
      .attr('fill', node => STATUS_META[node.status].color);

    nodeSelection.append('circle')
      .attr('class', 'visited-ring')
      .attr('r', 17)
      .attr('fill', 'none')
      .attr('stroke', '#55d6be')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '3 3');

    nodeSelection.append('text')
      .attr('x', 15)
      .attr('y', 4)
      .text(node => shortLabel(node.title));

    nodeSelection.append('title')
      .text(node => `${node.title}\n${node.module_title}\n${STATUS_META[node.status].label}`);

    const drag = d3.drag<SVGGElement, SimNode>()
      .on('start', (event, node) => {
        if (!event.active) simulation?.alphaTarget(0.25).restart();
        node.fx = node.x;
        node.fy = node.y;
      })
      .on('drag', (event, node) => {
        node.fx = event.x;
        node.fy = event.y;
      })
      .on('end', (event, node) => {
        if (!event.active) simulation?.alphaTarget(0);
        node.fx = null;
        node.fy = null;
      });
    nodeSelection.call(drag);

    simulation = d3.forceSimulation<SimNode, SimLink>(nodes)
      .force('link', d3.forceLink<SimNode, SimLink>(links).id(node => node.id).distance(82).strength(0.32))
      .force('charge', d3.forceManyBody<SimNode>().strength(-210))
      .force('collision', d3.forceCollide<SimNode>().radius(30).strength(0.9))
      .force('x', d3.forceX<SimNode>(node => modulePosition.get(node.module_id)?.x ?? width / 2).strength(0.12))
      .force('y', d3.forceY<SimNode>(node => modulePosition.get(node.module_id)?.y ?? height / 2).strength(0.14))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .on('tick', () => {
        linkSelection
          ?.attr('x1', link => (link.source as SimNode).x ?? 0)
          .attr('y1', link => (link.source as SimNode).y ?? 0)
          .attr('x2', link => (link.target as SimNode).x ?? 0)
          .attr('y2', link => (link.target as SimNode).y ?? 0);
        nodeSelection?.attr('transform', node => `translate(${node.x ?? 0},${node.y ?? 0})`);
      });

    updateGraphStyles();
  }

  onMount(() => {
    let cancelled = false;
    try {
      const stored = JSON.parse(localStorage.getItem('archon.visual-learning.visited') || '[]');
      if (Array.isArray(stored)) visited = new Set(stored.filter(value => typeof value === 'string'));
    } catch {
      visited = new Set();
    }
    void loadLearningGraph()
      .then(async payload => {
        if (cancelled) return;
        graph = payload;
        activeTourId = payload.tours[0]?.id ?? '';
        tourStep = 0;
        selectedId = payload.tours[0]?.concept_ids[0] ?? payload.nodes[0]?.id ?? '';
        loading = false;
        await tick();
        initializeGraph();
      })
      .catch(cause => {
        error = cause instanceof Error ? cause.message : 'Unable to load the visual learning graph';
        loading = false;
      });
    return () => {
      cancelled = true;
      simulation?.stop();
    };
  });

  $effect(() => {
    query;
    statusFilter;
    moduleFilter;
    activeTourId;
    tourStep;
    selectedId;
    visited;
    updateGraphStyles();
  });
</script>

<div class="min-h-full bg-[var(--bg)] text-[var(--text)]">
  <header class="border-b border-[var(--border)] bg-[radial-gradient(circle_at_top_left,rgba(85,214,190,.12),transparent_38%),var(--panel)] px-4 py-6 md:px-8">
    <div class="mx-auto flex max-w-[1600px] flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
      <div class="max-w-3xl">
        <div class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-[var(--accent)]">
          <Sparkles size={15} /> Visual Learning Studio
        </div>
        <h1 class="m-0 text-2xl font-semibold tracking-tight md:text-3xl">Explore Archon as a living concept map</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-[var(--secondary)]">Move from concepts to code, tests, evidence, and limitations. The graph is generated from canonical course documentation — not maintained as a second source of truth.</p>
      </div>
      {#if graph}
        <div class="grid grid-cols-4 gap-2" aria-label="Learning graph summary">
          <div class="rounded-xl border border-[var(--border)] bg-[rgba(8,11,16,.55)] px-3 py-2 text-center"><strong class="block font-mono text-lg">{graph.stats.concepts}</strong><span class="text-[10px] uppercase tracking-wider text-[var(--muted)]">Concepts</span></div>
          <div class="rounded-xl border border-[rgba(85,214,190,.28)] bg-[rgba(85,214,190,.07)] px-3 py-2 text-center"><strong class="block font-mono text-lg text-[var(--accent)]">{graph.stats.statuses.implemented}</strong><span class="text-[10px] uppercase tracking-wider text-[var(--muted)]">Built</span></div>
          <div class="rounded-xl border border-[rgba(240,189,98,.3)] bg-[rgba(240,189,98,.07)] px-3 py-2 text-center"><strong class="block font-mono text-lg text-[var(--warning)]">{graph.stats.statuses.partial}</strong><span class="text-[10px] uppercase tracking-wider text-[var(--muted)]">Partial</span></div>
          <div class="rounded-xl border border-[var(--border)] bg-[rgba(127,139,155,.07)] px-3 py-2 text-center"><strong class="block font-mono text-lg text-[var(--muted)]">{graph.stats.statuses.deferred}</strong><span class="text-[10px] uppercase tracking-wider text-[var(--muted)]">Deferred</span></div>
        </div>
      {/if}
    </div>
  </header>

  <main class="mx-auto flex max-w-[1600px] flex-col gap-4 p-3 md:p-6">
    {#if loading}
      <div class="grid min-h-[60vh] place-items-center rounded-2xl border border-[var(--border)] bg-[var(--panel)] text-sm text-[var(--muted)]">Building the concept graph…</div>
    {:else if error}
      <div class="rounded-xl border border-[rgba(255,107,114,.4)] bg-[rgba(255,107,114,.08)] p-4 text-sm text-[var(--danger)]" role="alert">{error}</div>
    {:else if graph}
      <section class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-3 md:p-4" aria-label="Map controls">
        <div class="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(220px,1fr)_240px_auto]">
          <label class="relative block">
            <span class="sr-only">Search concepts</span>
            <Search class="pointer-events-none absolute left-3 top-3 text-[var(--muted)]" size={17}/>
            <input bind:value={query} oninput={clearTour} type="search" placeholder="Search runtime, RAG, approvals…" class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] py-2 pl-10 pr-3 text-sm text-[var(--text)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[rgba(85,214,190,.14)]"/>
          </label>
          <label>
            <span class="sr-only">Filter by module</span>
            <select bind:value={moduleFilter} onchange={clearTour} class="min-h-11 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm text-[var(--secondary)] outline-none focus:border-[var(--accent)]">
              <option value="">All 15 modules</option>
              {#each graph.modules as module}
                <option value={module.id}>{module.id.replace(/^[0-9]+-/, '')} · {module.concept_count}</option>
              {/each}
            </select>
          </label>
          <div class="flex min-w-0 gap-2 overflow-x-auto pb-1 lg:pb-0" aria-label="Filter by capability status">
            {#each ['all', 'implemented', 'partial', 'deferred'] as status}
              <button onclick={() => { statusFilter = status as ConceptStatus | 'all'; clearTour(); }} aria-pressed={statusFilter === status} class="min-h-11 shrink-0 rounded-lg border px-3 text-xs font-semibold capitalize transition {statusFilter === status ? 'border-[var(--accent)] bg-[rgba(85,214,190,.12)] text-[var(--accent)]' : 'border-[var(--border)] bg-[var(--bg)] text-[var(--muted)] hover:text-[var(--text)]'}">{status}</button>
            {/each}
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--muted)]">
          <span><strong class="text-[var(--text)]">{visibleNodes.length}</strong> concepts visible · <strong class="text-[var(--accent)]">{visited.size}</strong> explored</span>
          <div class="flex gap-2">
            <button onclick={resetProgress} class="min-h-11 rounded-lg border border-[var(--border)] px-3 hover:text-[var(--text)]">Reset progress</button>
            <button onclick={resetFilters} class="flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border)] px-3 hover:text-[var(--text)]"><RotateCcw size={14}/> Reset view filters</button>
          </div>
        </div>
      </section>

      <section class="rounded-2xl border border-[var(--border)] bg-[linear-gradient(135deg,rgba(127,167,255,.07),rgba(85,214,190,.04))] p-3 md:p-4" aria-labelledby="journeys-title">
        <div class="mb-3 flex items-center justify-between gap-3">
          <div><h2 id="journeys-title" class="m-0 text-sm font-semibold">Guided journeys</h2><p class="mt-1 text-xs text-[var(--muted)]">Follow a curated learning path across module boundaries.</p></div>
          {#if activeTour}<button onclick={clearTour} class="min-h-11 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)]">Exit journey</button>{/if}
        </div>
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {#each graph.tours as tour}
            <button onclick={() => startTour(tour.id)} aria-pressed={activeTourId === tour.id} class="min-h-16 rounded-xl border p-3 text-left transition {activeTourId === tour.id ? 'border-[var(--warning)] bg-[rgba(240,189,98,.09)]' : 'border-[var(--border)] bg-[rgba(8,11,16,.45)] hover:border-[var(--accent)]'}">
              <strong class="block text-sm">{tour.title}</strong><span class="mt-1 block text-xs leading-5 text-[var(--muted)]">{tour.concept_ids.length} steps</span>
            </button>
          {/each}
        </div>
        {#if activeTour}
          <div class="mt-3 flex flex-col gap-3 rounded-xl border border-[rgba(240,189,98,.28)] bg-[rgba(8,11,16,.6)] p-3 sm:flex-row sm:items-center">
            <button onclick={() => moveTour(-1)} disabled={tourStep === 0} aria-label="Previous journey step" class="grid size-11 shrink-0 place-items-center rounded-lg border border-[var(--border)] disabled:opacity-35"><ChevronLeft size={18}/></button>
            <div class="min-w-0 flex-1"><span class="font-mono text-[10px] uppercase tracking-wider text-[var(--warning)]">Step {tourStep + 1} of {activeTour.concept_ids.length}</span><strong class="mt-1 block truncate text-sm">{selectedNode?.title}</strong><p class="mt-1 text-xs text-[var(--muted)]">{activeTour.description}</p></div>
            <button onclick={() => moveTour(1)} disabled={tourStep === activeTour.concept_ids.length - 1} aria-label="Next journey step" class="grid size-11 shrink-0 place-items-center rounded-lg border border-[var(--border)] disabled:opacity-35"><ChevronRight size={18}/></button>
          </div>
        {/if}
      </section>

      <div class="grid min-h-[720px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section class="relative min-h-[540px] overflow-hidden rounded-2xl border border-[var(--border)] bg-[#080b10] xl:min-h-[720px]" aria-label="Interactive concept graph">
          <div class="absolute left-3 top-3 z-10 flex gap-2">
            <button onclick={() => zoomBy(1.25)} aria-label="Zoom in" class="grid size-11 place-items-center rounded-lg border border-[var(--border)] bg-[rgba(16,21,29,.92)] text-sm">+</button>
            <button onclick={() => zoomBy(0.8)} aria-label="Zoom out" class="grid size-11 place-items-center rounded-lg border border-[var(--border)] bg-[rgba(16,21,29,.92)] text-sm">−</button>
            <button onclick={resetView} aria-label="Reset graph position" class="grid size-11 place-items-center rounded-lg border border-[var(--border)] bg-[rgba(16,21,29,.92)]"><Focus size={16}/></button>
          </div>
          <div class="absolute bottom-3 left-3 z-10 flex flex-wrap gap-3 rounded-lg border border-[var(--border)] bg-[rgba(16,21,29,.9)] px-3 py-2 text-[10px] text-[var(--muted)]" aria-label="Status legend">
            {#each Object.entries(STATUS_META) as [status, meta]}
              <span class="flex items-center gap-1.5"><i class="size-2 rounded-full" style={`background:${meta.color}`}></i>{meta.label}</span>
            {/each}
          </div>
          <svg bind:this={svgElement} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" class="h-full min-h-[540px] w-full touch-none" aria-labelledby="graph-title graph-description">
            <title id="graph-title">Archon interactive concept graph</title>
            <desc id="graph-description">Sixty-six concepts connected by modules and guided learning journeys. Select a node to inspect sources, tests, evidence, and limitations.</desc>
          </svg>
        </section>

        <aside class="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 xl:max-h-[720px] xl:overflow-y-auto" aria-label="Selected concept details">
          {#if selectedNode}
            <div class="mb-4 flex items-start justify-between gap-3">
              <div><span class="font-mono text-[10px] uppercase tracking-wider text-[var(--muted)]">{selectedNode.module_id.replace(/-/g, ' ')}</span><h2 class="mt-1 text-xl font-semibold leading-tight">{selectedNode.title}</h2></div>
              <span class="shrink-0 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-wider" style={`border-color:${STATUS_META[selectedNode.status].color}66;color:${STATUS_META[selectedNode.status].color};background:${STATUS_META[selectedNode.status].color}12`}>{STATUS_META[selectedNode.status].label}</span>
            </div>
            <section class="mb-4"><h3 class="section-heading"><BookOpen size={14}/> Beginner explanation</h3><p class="detail-copy">{selectedNode.summary}</p>{#if selectedNode.mental_model}<div class="mt-3 rounded-xl border border-[rgba(127,167,255,.24)] bg-[rgba(127,167,255,.07)] p-3"><span class="font-mono text-[10px] uppercase tracking-wider text-[#9bb9ff]">Mental model</span><p class="detail-copy mb-0 mt-1">{selectedNode.mental_model}</p></div>{/if}</section>
            <section class="mb-4"><h3 class="section-heading"><GitBranch size={14}/> Reality boundary</h3><p class="detail-copy">{selectedNode.limitations}</p></section>
            <a href={selectedNode.detail_href} target="_blank" rel="noopener" class="mb-5 flex min-h-11 items-center justify-between rounded-xl border border-[var(--border)] bg-[var(--panel-2)] px-3 text-sm text-[var(--text)] no-underline hover:border-[var(--accent)]"><span>{selectedNode.content_source === 'concept' ? 'Open concept page' : 'Open module fallback'}</span><ExternalLink size={15}/></a>

            {#each detailSections as section}
              <section class="mb-4">
                <h3 class="section-heading">{section.heading}</h3>
                {#if section.links.length}
                  <div class="space-y-2">{#each section.links as link}<a href={link.href} target="_blank" rel="noopener" class="flex min-h-11 items-center justify-between gap-3 rounded-lg border border-[var(--border)] px-3 text-xs text-[var(--secondary)] no-underline hover:border-[var(--accent)] hover:text-[var(--text)]"><span class="min-w-0 truncate font-mono">{link.path}</span><ExternalLink class="shrink-0" size={13}/></a>{/each}</div>
                {:else}<p class="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted)]">No separate {section.heading.toLowerCase()} mapping is recorded for this concept.</p>{/if}
              </section>
            {/each}
            {#if visited.has(selectedNode.id)}<div class="flex items-center gap-2 rounded-lg bg-[rgba(85,214,190,.08)] p-3 text-xs text-[var(--accent)]"><Check size={15}/> Explored on this device</div>{/if}
          {:else}
            <div class="grid h-full min-h-64 place-items-center text-center text-sm text-[var(--muted)]">Select a concept to inspect its learning contract.</div>
          {/if}
        </aside>
      </div>
    {/if}
  </main>
</div>

<style>
  :global(.concept-link) {
    vector-effect: non-scaling-stroke;
    transition: opacity 160ms ease, stroke 160ms ease, stroke-width 160ms ease;
  }
  :global(.concept-node) { cursor: pointer; outline: none; transition: opacity 160ms ease; }
  :global(.concept-node circle:first-of-type) { filter: drop-shadow(0 0 8px rgba(85, 214, 190, 0.12)); transition: r 160ms ease, stroke 160ms ease; }
  :global(.concept-node text) { fill: #dbe5ef; font: 600 11px var(--font-mono); paint-order: stroke; stroke: #080b10; stroke-width: 3px; stroke-linejoin: round; pointer-events: none; }
  :global(.concept-node .visited-ring) { opacity: 0; }
  :global(.concept-node.is-visited .visited-ring) { opacity: 0.65; }
  :global(.concept-node.is-selected text) { fill: #ffffff; font-size: 12px; }
  :global(.concept-node:focus circle:first-of-type) { stroke: #ffffff; stroke-width: 3px; }
  .section-heading { display: flex; align-items: center; gap: 0.45rem; margin: 0 0 0.5rem; color: var(--text); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }
  .detail-copy { margin: 0; color: var(--secondary); font-size: 0.82rem; line-height: 1.65; }
</style>
