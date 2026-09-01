<script lang="ts">
 import { Braces, FileText, Package, ShieldCheck } from 'lucide-svelte';
 import { getRunEffectiveContext, type EffectiveContextManifest, type EffectiveContextEntry } from '$lib/runs';
 let { runId }: { runId: string } = $props();
 let manifest:EffectiveContextManifest|null=$state(null);let loading=$state(true);let error=$state('');
 async function load(){loading=true;error='';manifest=null;try{manifest=await getRunEffectiveContext(runId)}catch(e){error=e instanceof Error?e.message:'Effective context unavailable'}finally{loading=false}}
 $effect(()=>{runId;queueMicrotask(()=>void load())});
 const short=(value?:string|null)=>value?(value.length>14?`${value.slice(0,12)}…`:value):'—';
 const label=(item:EffectiveContextEntry)=>item.relative_path||item.name||item.id;
 const reason=(item:EffectiveContextEntry)=>item.selection_reason||item.reason||'Selected by deterministic resolver';
</script>
<div data-testid="effective-context">
 {#if loading}<div class="empty-detail" aria-live="polite">Loading effective context…</div>
 {:else if error}<div class="empty-detail" role="alert">{error}<button class="ml-2 text-[var(--accent)] underline" onclick={load}>Retry</button></div>
 {:else if manifest}<div class="space-y-3">
  <div class="stat-grid"><div><span>Instructions</span><strong>{manifest.instruction_revisions.length}</strong></div><div><span>Skills</span><strong>{manifest.skill_revisions.length}</strong></div><div><span>Capabilities</span><strong>{manifest.capabilities.length}</strong></div><div><span>Context cost</span><strong>{manifest.context_cost.estimated_tokens.toLocaleString()}</strong><small class="text-[var(--muted)]">tokens</small></div></div>
  {#each [{title:'Instruction revisions',items:manifest.instruction_revisions,icon:FileText},{title:'Skill revisions',items:manifest.skill_revisions,icon:Package},{title:'Exposed capabilities',items:manifest.capabilities,icon:Braces}] as group}<details class="rounded-lg border border-[var(--border)] bg-[var(--panel-2)]" open={group.title==='Instruction revisions'}><summary class="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 text-xs font-semibold"><group.icon size={14} class="text-[var(--accent)]"/>{group.title}<span class="ml-auto text-[var(--muted)]">{group.items.length}</span></summary>{#if !group.items.length}<p class="border-t border-[var(--border)] p-3 text-xs text-[var(--muted)]">None selected.</p>{:else}<div class="border-t border-[var(--border)]">{#each group.items as item}<div class="border-b border-[var(--border)] p-3 text-xs last:border-0"><div class="flex justify-between gap-2"><strong class="truncate" title={label(item)}>{label(item)}</strong><span class="font-mono text-[var(--muted)]">{item.revision||item.version||''}</span></div><p class="my-1 text-[var(--secondary)]">{reason(item)}</p><div class="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-[var(--muted)]">{#if item.content_hash}<span title={item.content_hash}>content {short(item.content_hash)}</span>{/if}{#if item.schema_hash}<span title={item.schema_hash}>schema {short(item.schema_hash)}</span>{/if}{#if item.permission}<span>policy {item.permission}</span>{/if}{#if item.estimated_tokens!=null}<span>{item.estimated_tokens} tokens</span>{/if}</div></div>{/each}</div>{/if}</details>{/each}
  {#if manifest.omission_reasons.length}<details class="rounded-lg border border-[var(--border)] bg-[var(--panel-2)]"><summary class="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 text-xs font-semibold">Omissions <span class="ml-auto">{manifest.omission_reasons.length}</span></summary><ul class="m-0 border-t border-[var(--border)] p-3 pl-7 text-xs text-[var(--muted)]">{#each manifest.omission_reasons as reason}<li>{reason}</li>{/each}</ul></details>{/if}
  <p class="flex gap-2 text-[11px] leading-4 text-[var(--muted)]"><ShieldCheck size={14} class="shrink-0"/>Metadata-only provenance: revisions, hashes, policy decisions, selection reasons, and cost. Hidden reasoning and secret values are never shown.</p>
 </div>{/if}
</div>
