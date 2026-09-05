<script lang="ts">
  import {
    SvelteFlow,
    Controls,
    Background,
    BackgroundVariant,
    MarkerType,
    type Node,
    type Edge,
    type NodeTypes
  } from '@xyflow/svelte';
  import '@xyflow/svelte/dist/style.css';
  import LearningNodeCard from './LearningNodeCard.svelte';
  import TeachingInspector from './TeachingInspector.svelte';
  import type { LearningEdge, LearningNode } from '$lib/learning-teaching';
  import { ARCHON_THEME, LEARNING_KIND_COLORS } from '$lib/archon-theme';

  let { graphNodes, graphEdges, sourceCommit, layout='flow' }: { graphNodes:LearningNode[]; graphEdges:LearningEdge[]; sourceCommit:string; layout?:'flow'|'radial' } = $props();
  let selectedNodeId=$state('');
  let selectedEdgeId=$state('');

  const nodeTypes:NodeTypes={learning:LearningNodeCard};
  const colors=LEARNING_KIND_COLORS;

  function nodePosition(index:number,node:LearningNode){
    if(node.position)return node.position;
    const columns=3;
    return {x:(index%columns)*360,y:Math.floor(index/columns)*220};
  }

  let positioned=$derived(graphNodes.map((node,index)=>({...node,position:nodePosition(index,node)})));
  let nodes=$derived(positioned.map((node,index):Node=>({
    id:node.id,
    type:'learning',
    position:node.position,
    data:{label:node.label,color:colors[node.kind]??'#94a3b8',sequence:layout==='flow'?index+1:undefined},
    draggable:false,
    selectable:true,
    focusable:true,
    zIndex:5,
    style:`width:${layout==='radial'?190:180}px;background:transparent;border:0;padding:0;box-shadow:none;`
  })));

  function side(dx:number,dy:number){
    if(Math.abs(dx)>=Math.abs(dy))return dx>=0?['right-source','left-target']:['left-source','right-target'];
    if(dy>=0)return [dx < -30?'bottom-left-source':dx > 30?'bottom-right-source':'bottom-source','top-target'];
    return [dx < -30?'top-left-source':dx > 30?'top-right-source':'top-source','bottom-target'];
  }

  let edges=$derived(graphEdges.map((edge,index):Edge=>{
    const source=positioned.find(node=>node.id===edge.source);
    const target=positioned.find(node=>node.id===edge.target);
    const dx=(target?.position.x??0)-(source?.position.x??0);
    const dy=(target?.position.y??0)-(source?.position.y??0);
    const [sourceHandle,targetHandle]=side(dx,dy);
    return {
      id:edge.id??`${edge.source}-${edge.target}-${index}`,
      source:edge.source,
      target:edge.target,
      sourceHandle,
      targetHandle,
      type:layout==='radial'?'straight':'smoothstep',
      label:edge.label,
      focusable:true,
      selectable:true,
      zIndex:0,
      animated:edge.style==='approval',
      markerEnd:{type:MarkerType.ArrowClosed,color:ARCHON_THEME.orange},
      style:`stroke:${ARCHON_THEME.orange};stroke-width:2.5`,
      labelStyle:'color:#f8fafc;font-size:11px;font-weight:700'
    };
  }));

  let selectedNode=$derived(graphNodes.find(node=>node.id===selectedNodeId));
  let selectedEdge=$derived(graphEdges.find((edge,index)=>(edge.id??`${edge.source}-${edge.target}-${index}`)===selectedEdgeId));
  function chooseNode(event:{node:Node}){selectedNodeId=event.node.id;selectedEdgeId=''}
  function chooseEdge(event:{edge:Edge}){selectedEdgeId=event.edge.id;selectedNodeId=''}
</script>

<div class="graph-shell" class:radial={layout==='radial'}>
  <div class="canvas" aria-label="Interactive connected diagram">
    <SvelteFlow {nodes} {edges} {nodeTypes} fitView fitViewOptions={{padding:layout === 'radial' ? .28 : .2,maxZoom:layout === 'radial' ? .9 : 1}} nodesDraggable={false} nodesConnectable={false} onnodeclick={chooseNode} onedgeclick={chooseEdge}>
      <Controls showLock={false}/><Background variant={BackgroundVariant.Dots} gap={22} size={1}/>
    </SvelteFlow>
  </div>
  {#if selectedNode}
    <TeachingInspector eyebrow="Selected component" title={selectedNode.label} summary={selectedNode.summary} nodeTeaching={selectedNode.teaching} moduleDetails={selectedNode.details} sources={selectedNode.sources} {sourceCommit}/>
  {:else if selectedEdge}
    <TeachingInspector eyebrow="Selected transition" title={selectedEdge.label||'Concept relationship'} edgeTeaching={selectedEdge.teaching} moduleDetails={selectedEdge.explanation} sources={selectedEdge.sources} {sourceCommit}/>
  {:else}
    <aside class="explanation"><span class="eyebrow">Explore the process</span><h4>Select a node or arrow</h4><p>Click or keyboard-focus a component or connection to inspect its responsibility, inputs, outputs, guarantees, failure behavior, and architectural purpose.</p></aside>
  {/if}
</div>
<details class="steps"><summary>Read the diagram as steps</summary><ol>{#each graphEdges as edge,index}<li><button onclick={()=>{selectedEdgeId=edge.id??`${edge.source}-${edge.target}-${index}`;selectedNodeId=''}}><strong>{graphNodes.find(node=>node.id===edge.source)?.label??edge.source}</strong>{#if edge.label} <span>{edge.label}</span>{/if} <strong>{graphNodes.find(node=>node.id===edge.target)?.label??edge.target}</strong></button>{#if edge.explanation}<p>{edge.explanation}</p>{/if}</li>{/each}</ol></details>

<style>
  .graph-shell{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(230px,.62fr);gap:.85rem}.graph-shell.radial{grid-template-columns:1fr}.canvas{height:600px;border:1px solid var(--archon-border,var(--border));border-radius:.9rem;overflow:hidden;background:var(--archon-canvas,#050b16)}.radial .canvas{height:680px}.explanation{border:1px solid var(--border);border-radius:.9rem;background:var(--panel);padding:1rem;min-height:180px}.radial .explanation{min-height:0}.explanation h4{margin:.45rem 0;font-size:1.15rem}.explanation p{color:var(--secondary);line-height:1.6;font-size:.84rem}.steps{margin-top:.85rem;border:1px solid var(--border);border-radius:.75rem;padding:.8rem;color:var(--secondary);font-size:.8rem}.steps summary{cursor:pointer;color:var(--text);font-weight:700}.steps ol{display:grid;gap:.65rem}.steps button{border:0;background:none;color:var(--text);padding:0;text-align:left;cursor:pointer}.steps button:hover,.steps button:focus-visible{text-decoration:underline;text-decoration-color:var(--accent);text-underline-offset:3px}.steps li span{color:var(--accent);font-weight:700}.steps p{margin:.25rem 0 0;color:var(--muted)}:global(.svelte-flow__node:focus-visible),:global(.svelte-flow__edge:focus-visible){outline:3px solid var(--archon-orange,#f59e0b);outline-offset:3px;filter:drop-shadow(0 0 9px rgba(245,158,11,.55))}:global(.svelte-flow__controls){background:#0f172a;border-color:#334155}:global(.svelte-flow__controls-button){background:#0f172a;color:#e2e8f0;border-color:#334155}:global(.svelte-flow__edge-label){z-index:10!important;background:#0f172a!important;color:#f8fafc!important;border:1px solid #475569;border-radius:5px;padding:3px 6px;box-shadow:0 0 0 5px #0f172a,0 2px 8px rgba(0,0,0,.45);white-space:nowrap}@media(max-width:850px){.graph-shell{grid-template-columns:1fr}.canvas,.radial .canvas{height:520px}}@media(max-width:520px){.canvas,.radial .canvas{height:480px}.explanation{min-height:0}}
</style>
