<script lang="ts">
  import type { TutorDiagram } from '$lib/learning-tutor';

  let { diagram }: { diagram: TutorDiagram } = $props();
  const width = 560;
  const top = 24;
  const step = 104;
  let ordered = $derived(
    diagram.reading_order
      .map(id => diagram.nodes.find(node => node.id === id))
      .filter((node): node is TutorDiagram['nodes'][number] => Boolean(node)),
  );
  let height = $derived(Math.max(130, top * 2 + ordered.length * step));
  function edgeLabel(from: string, to: string): string {
    return diagram.edges.find(edge => edge.from === from && edge.to === to)?.label ?? 'leads to';
  }
</script>

<figure class="diagram" aria-labelledby="tutor-diagram-title">
  <figcaption id="tutor-diagram-title">{diagram.title}</figcaption>
  <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="tutor-diagram-title">
    <defs>
      <marker id="tutor-arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
        <polygon points="0 0, 9 3.5, 0 7" fill="var(--accent)" />
      </marker>
    </defs>
    {#each ordered as node, index}
      {@const y = top + index * step}
      {#if index > 0}
        <line x1="280" y1={y - 34} x2="280" y2={y} stroke="var(--accent)" stroke-width="2" marker-end="url(#tutor-arrow)" />
        <text x="292" y={y - 12} fill="var(--muted)" font-size="11">{edgeLabel(ordered[index - 1].id, node.id)}</text>
      {/if}
      <rect x="80" y={y} width="400" height="66" rx="10" fill="var(--bg)" stroke="var(--accent)" stroke-width="1.5" />
      <text x="280" y={y + 29} text-anchor="middle" fill="var(--text)" font-size="14" font-weight="700">{node.label}</text>
      <text x="280" y={y + 50} text-anchor="middle" fill="var(--muted)" font-size="10">{node.evidence_ids.join(' · ')}</text>
    {/each}
  </svg>
  <ol class="sr-only">
    {#each ordered as node, index}
      <li>{node.label}{#if index < ordered.length - 1}: {edgeLabel(node.id, ordered[index + 1].id)}{/if}</li>
    {/each}
  </ol>
</figure>

<style>
  .diagram{margin:1rem 0;border:1px solid var(--border);border-radius:.8rem;background:var(--panel);padding:.75rem}.diagram figcaption{font-weight:700;color:var(--text);margin-bottom:.5rem}.diagram svg{display:block;width:100%;max-height:520px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
</style>
