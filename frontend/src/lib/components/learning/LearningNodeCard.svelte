<script lang="ts">
  import { Handle, Position, type NodeProps } from '@xyflow/svelte';
  let { data }: NodeProps = $props();
</script>

<div class="node-card" style={`--node-color:${data.color}`}>
  {#if data.sequence}<span class="sequence" aria-hidden="true">{data.sequence}</span>{/if}
  <span>{data.label}</span>
</div>

<Handle type="target" position={Position.Left} id="left-target" />
<Handle type="source" position={Position.Left} id="left-source" />
<Handle type="target" position={Position.Right} id="right-target" />
<Handle type="source" position={Position.Right} id="right-source" />
<Handle type="target" position={Position.Top} id="top-target" />
<Handle type="source" position={Position.Top} id="top-source" />
<Handle type="target" position={Position.Top} id="top-left-target" style="left:25%" />
<Handle type="source" position={Position.Top} id="top-left-source" style="left:25%" />
<Handle type="target" position={Position.Top} id="top-right-target" style="left:75%" />
<Handle type="source" position={Position.Top} id="top-right-source" style="left:75%" />
<Handle type="target" position={Position.Bottom} id="bottom-target" />
<Handle type="source" position={Position.Bottom} id="bottom-source" />
<Handle type="target" position={Position.Bottom} id="bottom-left-target" style="left:25%" />
<Handle type="source" position={Position.Bottom} id="bottom-left-source" style="left:25%" />
<Handle type="target" position={Position.Bottom} id="bottom-right-target" style="left:75%" />
<Handle type="source" position={Position.Bottom} id="bottom-right-source" style="left:75%" />

<style>
  .node-card{position:relative;display:flex;align-items:center;justify-content:center;min-height:48px;padding:.85rem 1rem;border:2px solid var(--node-color);border-radius:.75rem;background:#0a1022;color:#f4f7fb;font-weight:750;text-align:center;box-shadow:0 8px 22px rgba(2,6,23,.38)}
  .sequence{position:absolute;top:-11px;left:-11px;display:grid;place-items:center;width:25px;height:25px;border-radius:999px;background:var(--node-color);color:#020617;font:800 .68rem var(--font-mono);box-shadow:0 0 0 3px #020617}
  :global(.svelte-flow__handle){opacity:0!important;width:1px!important;height:1px!important;min-width:1px!important;min-height:1px!important;border:0!important;background:transparent!important}
</style>
