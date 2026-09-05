<script lang="ts">
  import LearningGraph from './LearningGraph.svelte';
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';
  type MapNode={id:string;label:string;summary:string;details?:string;sources:SourceReference[];children:MapNode[]};
  type Positioned=MapNode&{kind:string;position:{x:number;y:number}};
  let { root, sourceCommit }: { root:MapNode;sourceCommit:string }=$props();
  let expandedId=$state('');
  let expanded=$derived(root.children.find(branch=>branch.id===expandedId)??root.children[0]);

  function radialNodes():Positioned[]{
    const center={x:440,y:350};
    const result:Positioned[]=[{...root,kind:'root',position:center}];
    root.children.forEach((branch,branchIndex)=>{
      const angle=(branchIndex/root.children.length)*Math.PI*2-Math.PI/2;
      result.push({...branch,kind:'backend',position:{x:center.x+Math.cos(angle)*310,y:center.y+Math.sin(angle)*235}});
      if(branch.id===expanded?.id){
        branch.children.forEach((child,childIndex)=>{
          const spread=(childIndex-(branch.children.length-1)/2)*.48;
          result.push({...child,kind:'external',position:{x:center.x+Math.cos(angle+spread)*525,y:center.y+Math.sin(angle+spread)*405}});
        });
      }
    });
    return result;
  }
  function graphEdges(){
    const first=root.children.map(branch=>({id:`${root.id}-${branch.id}`,source:root.id,target:branch.id,label:'',explanation:`${branch.label} is one major stage of ${root.label}. ${branch.summary}`,sources:branch.sources}));
    if(!expanded)return first;
    const children=expanded.children.map(child=>({id:`${expanded.id}-${child.id}`,source:expanded.id,target:child.id,label:'',explanation:`${child.label} belongs to ${expanded.label}. ${child.summary}`,sources:child.sources}));
    return [...first,...children];
  }
  let nodes=$derived(radialNodes());
  let edges=$derived(graphEdges());
</script>

<section class="mind-map" aria-labelledby="mind-map-title">
  <header><span class="eyebrow">Connected concept map</span><h3 id="mind-map-title">{root.label}</h3><p>{root.summary}</p></header>
  <div class="branch-picker" aria-label="Expand a mind-map branch"><span>Expand a branch</span>{#each root.children as branch}<button aria-pressed={expanded?.id===branch.id} onclick={()=>expandedId=branch.id}>{branch.label}</button>{/each}</div>
  <LearningGraph graphNodes={nodes} graphEdges={edges} {sourceCommit} layout="radial" />
  <SourceLinks sources={root.sources} {sourceCommit} heading="Mind-map foundation" />
</section>

<style>.mind-map{border:1px solid var(--border);border-radius:1rem;background:var(--archon-canvas,#050b16);padding:1rem}.mind-map header{margin-bottom:1rem}.mind-map h3{font-size:1.7rem;margin:.4rem 0}.mind-map header p{margin:.35rem 0;color:var(--secondary);line-height:1.6}.branch-picker{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;margin-bottom:.8rem}.branch-picker>span{color:var(--muted);font:700 .65rem var(--font-mono);text-transform:uppercase;margin-right:.35rem}.branch-picker button{border:1px solid var(--border);border-radius:999px;background:var(--panel);color:var(--secondary);padding:.45rem .65rem;font-size:.7rem}.branch-picker button[aria-pressed="true"]{border-color:var(--accent);background:var(--accent-glow);color:var(--accent);box-shadow:0 0 14px var(--archon-orange-glow)}@media(max-width:600px){.branch-picker{align-items:stretch}.branch-picker>span{width:100%}}
</style>
