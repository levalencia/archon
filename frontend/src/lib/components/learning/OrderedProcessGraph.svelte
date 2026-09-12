<script lang="ts">
  import TeachingInspector from './TeachingInspector.svelte';
  import type { LearningEdge as GraphEdge, LearningNode as GraphNode } from '$lib/learning-teaching';
  import { COGENTREX_THEME, LEARNING_KIND_COLORS } from '$lib/cogentrex-theme';
  type Point={x:number;y:number};
  let { graphNodes, graphEdges, sourceCommit }: { graphNodes:GraphNode[];graphEdges:GraphEdge[];sourceCommit:string }=$props();
  let selectedNodeId=$state('');
  let selectedEdgeId=$state('');
  const width=1040,nodeWidth=190,nodeHeight=68;
  const xPositions=[70,425,780],yPositions=[64,278,492];
  const rowNames=['Ingress and identity','Bounded reasoning','Execution and evidence'];
  const colors=LEARNING_KIND_COLORS;
  let positions=$derived(new Map(graphNodes.map((node,index)=>[node.id,{x:xPositions[index%3],y:yPositions[Math.floor(index/3)]??492,index}])));
  let selectedNode=$derived(graphNodes.find(node=>node.id===selectedNodeId));
  let selectedEdge=$derived(graphEdges.find((edge,index)=>(edge.id??`${edge.source}-${edge.target}-${index}`)===selectedEdgeId));
  function chooseNode(id:string){selectedNodeId=id;selectedEdgeId=''}
  function chooseEdge(edge:GraphEdge,index:number){selectedEdgeId=edge.id??`${edge.source}-${edge.target}-${index}`;selectedNodeId=''}
  function activate(event:KeyboardEvent,action:()=>void){if(event.key==='Enter'||event.key===' '){event.preventDefault();action()}}
  function edgeGeometry(edge:GraphEdge):{path:string;label:Point}{
    const source=positions.get(edge.source);const target=positions.get(edge.target);
    if(!source||!target)return{path:'',label:{x:0,y:0}};
    const sourceRow=Math.floor(source.index/3),targetRow=Math.floor(target.index/3);
    if(sourceRow===targetRow){
      const x1=source.x+nodeWidth,x2=target.x,y=source.y+nodeHeight/2;
      return{path:`M ${x1} ${y} L ${x2} ${y}`,label:{x:(x1+x2)/2,y:y-13}};
    }
    const x1=source.x+nodeWidth,y1=source.y+nodeHeight/2;
    const x2=target.x,y2=target.y+nodeHeight/2;
    const gutterY=(source.y+nodeHeight+target.y)/2;
    return{path:`M ${x1} ${y1} L 1000 ${y1} L 1000 ${gutterY} L 38 ${gutterY} L 38 ${y2} L ${x2} ${y2}`,label:{x:520,y:gutterY-13}};
  }
</script>

<div class="ordered-shell">
  <div class="canvas" aria-label="Ordered request lifecycle diagram">
    <svg viewBox="0 0 1040 620" role="img" aria-labelledby="ordered-title ordered-description">
      <title id="ordered-title">Ordered request lifecycle</title>
      <desc id="ordered-description">A numbered left-to-right process arranged in three lanes with explicit continuation arrows between lanes.</desc>
      <defs>
        <pattern id="ordered-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#26324d"/></pattern>
        <marker id="ordered-arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z" fill={COGENTREX_THEME.orange}/></marker>
      </defs>
      <rect width="1040" height="620" fill={COGENTREX_THEME.canvas}/><rect width="1040" height="620" fill="url(#ordered-grid)" opacity=".55"/>
      {#each rowNames as name,row}
        <text x="70" y={yPositions[row]-22} fill="#a9b4cc" font-size="13" font-weight="700" letter-spacing="1.4">PHASE {row+1} · {name.toUpperCase()}</text>
      {/each}
      {#each graphEdges as edge,index}
        {@const geometry=edgeGeometry(edge)}
        <g class="edge" class:selected={selectedEdgeId===(edge.id??`${edge.source}-${edge.target}-${index}`)} role="button" tabindex="0" aria-label={`${edge.label}: ${edge.source} to ${edge.target}`} onclick={()=>chooseEdge(edge,index)} onkeydown={(event)=>activate(event,()=>chooseEdge(edge,index))}>
          <path class="hit" d={geometry.path}/><path class="line" d={geometry.path} marker-end="url(#ordered-arrow)"/>
          <rect x={geometry.label.x-68} y={geometry.label.y-15} width="136" height="25" rx="6"/><text x={geometry.label.x} y={geometry.label.y+2} text-anchor="middle">{edge.label}</text>
        </g>
      {/each}
      {#each graphNodes as node,index}
        {@const point=positions.get(node.id)}
        {#if point}
          <g class="node" class:selected={selectedNodeId===node.id} role="button" tabindex="0" aria-label={`Step ${index+1}: ${node.label}`} onclick={()=>chooseNode(node.id)} onkeydown={(event)=>activate(event,()=>chooseNode(node.id))}>
            <rect x={point.x} y={point.y} width={nodeWidth} height={nodeHeight} rx="12" fill="#0a1022" stroke={colors[node.kind]??'#a9b4cc'} stroke-width="2"/>
            <circle cx={point.x+3} cy={point.y+3} r="17" fill={colors[node.kind]??'#a9b4cc'}/>
            <text class="number" x={point.x+3} y={point.y+8} text-anchor="middle">{index+1}</text>
            <text class="node-label" x={point.x+nodeWidth/2} y={point.y+40} text-anchor="middle">{node.label}</text>
          </g>
        {/if}
      {/each}
    </svg>
  </div>
  {#if selectedNode}
    <TeachingInspector eyebrow="Selected component" title={selectedNode.label} summary={selectedNode.summary} nodeTeaching={selectedNode.teaching} moduleDetails={selectedNode.details} sources={selectedNode.sources} {sourceCommit}/>
  {:else if selectedEdge}
    <TeachingInspector eyebrow="Selected transition" title={selectedEdge.label} edgeTeaching={selectedEdge.teaching} moduleDetails={selectedEdge.explanation} sources={selectedEdge.sources} {sourceCommit}/>
  {:else}
    <aside class="explanation"><span class="eyebrow">One ordered path</span><h4>Read 1 through {graphNodes.length}</h4><p>Every lane reads left to right. Select any box or arrow to inspect its inputs, responsibility, guarantees, failure behavior, and reason for existing.</p></aside>
  {/if}
</div>
<details class="steps"><summary>Read the diagram as steps</summary><ol>{#each graphEdges as edge,index}<li><button onclick={()=>chooseEdge(edge,index)}><strong>{graphNodes.find(node=>node.id===edge.source)?.label}</strong> <span>{edge.label}</span> <strong>{graphNodes.find(node=>node.id===edge.target)?.label}</strong></button>{#if edge.explanation}<p>{edge.explanation}</p>{/if}</li>{/each}</ol></details>

<style>
  .ordered-shell{display:grid;grid-template-columns:1fr;gap:.85rem}.canvas{border:1px solid var(--cogentrex-border,var(--border));border-radius:.9rem;overflow:hidden;background:var(--cogentrex-canvas,#050712)}.canvas svg{display:block;width:100%;height:auto}.node,.edge{cursor:pointer}.node:focus-visible,.edge:focus-visible{outline:none}.node:focus-visible rect,.node.selected rect{stroke:var(--cogentrex-orange,#f6b44b);stroke-width:4;filter:drop-shadow(0 0 12px rgba(246,180,75,.55))}.node-label{fill:#f4f7fb;font-size:17px;font-weight:750}.number{fill:#050712;font:800 13px var(--font-mono)}.line{fill:none;stroke:var(--cogentrex-orange,#f6b44b);stroke-width:3;stroke-linejoin:round}.edge.selected .line{stroke:#fbbf24;stroke-width:5;filter:drop-shadow(0 0 8px rgba(246,180,75,.65))}.hit{fill:none;stroke:transparent;stroke-width:22}.edge rect{fill:#0a1022;stroke:#475569;stroke-width:1}.edge.selected rect{stroke:var(--cogentrex-orange,#f6b44b);stroke-width:2}.edge text{fill:#f4f7fb;font-size:12px;font-weight:700}.explanation{border:1px solid var(--border);border-radius:.9rem;background:var(--panel);padding:1rem;min-height:0}.explanation h4{margin:.45rem 0;font-size:1.15rem}.explanation p{color:var(--secondary);line-height:1.6;font-size:.84rem}.steps{margin-top:.85rem;border:1px solid var(--border);border-radius:.75rem;padding:.8rem;color:var(--secondary);font-size:.8rem}.steps summary{cursor:pointer;color:var(--text);font-weight:700}.steps ol{display:grid;gap:.65rem}.steps button{border:0;background:none;color:var(--text);padding:0;text-align:left;cursor:pointer}.steps button:hover,.steps button:focus-visible{text-decoration:underline;text-decoration-color:var(--accent);text-underline-offset:3px}.steps li span{color:var(--accent);font-weight:700}.steps p{margin:.25rem 0 0;color:var(--muted)}@media(max-width:850px){.canvas{overflow-x:auto}.canvas svg{min-width:760px}}
  @media(forced-colors:active){.node:focus-visible,.edge:focus-visible{outline:2px solid CanvasText}.node.selected rect,.edge.selected rect{stroke:Highlight}}
</style>
