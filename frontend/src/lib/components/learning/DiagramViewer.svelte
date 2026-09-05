<script lang="ts">
  import OrderedProcessGraph from './OrderedProcessGraph.svelte';
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';
  import type { LearningEdge as Edge, LearningNode as Node } from '$lib/learning-teaching';
  let { content, sourceCommit }: { content:{title:string;description:string;nodes:Node[];edges:Edge[];sources?:SourceReference[]}; sourceCommit:string }=$props();
</script>

<figure class="diagram" aria-labelledby="diagram-title" aria-describedby="diagram-description">
  <figcaption><span class="eyebrow">Connected process</span><h3 id="diagram-title">{content.title}</h3><p id="diagram-description">{content.description}</p></figcaption>
  <OrderedProcessGraph graphNodes={content.nodes} graphEdges={content.edges} {sourceCommit}/>
  {#if content.sources?.length}<SourceLinks sources={content.sources} {sourceCommit} heading="Diagram documentation" />{/if}
</figure>

<style>.diagram{margin:0;border:1px solid var(--border);border-radius:1rem;background:#07101f;padding:1rem}.diagram figcaption{margin-bottom:1rem}.diagram h3{margin:.35rem 0;font-size:1.35rem}.diagram figcaption p{margin:.35rem 0;color:var(--secondary);line-height:1.6}</style>
