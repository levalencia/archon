<script lang="ts">
  import { Package, ToggleLeft, ToggleRight } from 'lucide-svelte';
  import { bindSkill, listSkillCatalog, type SkillCatalogItem } from '$lib/skills';
  let { projectId }: { projectId: string } = $props();
  let skills: SkillCatalogItem[] = $state([]); let active = $state<'installed'|'available'|'enabled'>('installed');
  let loading = $state(true); let error = $state(''); let busy = $state(''); let generation=0;
  const filtered = $derived(skills.filter((s) => active === 'enabled' ? s.enabled : active === 'available' ? !s.enabled : true));
  async function load() { const scope=projectId;const current=++generation;loading=true; error=''; try { const next=await listSkillCatalog(scope);if(current===generation&&scope===projectId)skills=next; } catch(e){ if(current===generation)error=e instanceof Error?e.message:'Skills unavailable'; } finally{if(current===generation)loading=false;} }
  async function update(item: SkillCatalogItem, enabled: boolean, pinned: boolean){
    if (!item.revision_id) return;
    const scope=projectId;busy=item.id; error='';
    try { const next=await bindSkill(scope,item.id,item.revision_id,item.revision_owner_id,enabled,pinned); if(scope===projectId)skills=skills.map(s=>s.id===item.id?{...s,...next}:s); }
    catch(e){if(scope===projectId)error=e instanceof Error?e.message:'Update failed';} finally{if(scope===projectId)busy='';}
  }
  const tabs = ['installed','available','enabled'] as const;
  function onTabKey(event: KeyboardEvent) {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const current=tabs.indexOf(active);
    const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:
      (current+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    active=tabs[next];
    queueMicrotask(()=>document.getElementById(`skills-tab-${active}`)?.focus());
  }
  $effect(()=>{ projectId; queueMicrotask(()=>void load()); });
</script>
<section id="skills" aria-labelledby="skills-title" class="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-4 sm:p-5">
 <div><p class="eyebrow">Governed packages</p><h2 id="skills-title" class="mt-1 text-base font-semibold">Skills Catalog</h2><p class="mt-1 text-xs leading-5 text-[var(--muted)]">Enable reviewed, revision-pinned skills for this project.</p></div>
 <div class="mt-4 grid grid-cols-3 rounded-lg border border-[var(--border)] p-1" role="tablist" aria-label="Skill catalog filters">{#each tabs as tab}<button id={`skills-tab-${tab}`} role="tab" aria-selected={active===tab} aria-controls="skills-panel" tabindex={active===tab?0:-1} class="min-h-11 rounded-md px-2 text-xs capitalize {active===tab?'bg-[rgba(85,214,190,.12)] text-[var(--accent)]':'text-[var(--muted)]'}" onclick={()=>active=tab} onkeydown={onTabKey}>{tab}</button>{/each}</div>
 {#if error}<div class="mt-3 rounded-lg border border-[rgba(255,107,114,.4)] p-3 text-xs text-[var(--danger)]" role="alert">{error}<button class="ml-2 min-h-11 underline" onclick={load}>Retry</button></div>{/if}
 <div id="skills-panel" role="tabpanel" aria-labelledby={`skills-tab-${active}`} tabindex="0">
 {#if loading}<div class="mt-4 p-5 text-sm text-[var(--muted)]" aria-live="polite">Loading catalog…</div>{:else if !filtered.length}<div class="mt-4 rounded-lg border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--muted)]">No {active} skills.</div>{:else}<div class="mt-4 space-y-2">{#each filtered as item (item.id)}<article class="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--panel-2)] p-3"><div class="flex items-start gap-3"><Package size={17} class="mt-1 shrink-0 text-[var(--purple)]"/><div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><h3 class="text-sm font-semibold">{item.name}</h3><span class="break-all text-[10px] text-[var(--muted)]">v{item.version} · {item.source}</span>{#if item.pinned}<span class="rounded-full bg-[rgba(85,214,190,.1)] px-2 py-1 text-[10px] text-[var(--accent)]">Pinned</span>{/if}</div><p class="my-2 text-xs leading-5 text-[var(--secondary)]">{item.description}</p><div class="flex flex-wrap gap-1">{#each item.risk_classes as risk}<span class="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--muted)]">{risk}</span>{/each}<span class="rounded border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--muted)]">{item.trust_state}</span></div>{#if !item.revision_id}<p class="mt-2 text-[11px] text-[var(--warning)]">Binding unavailable until the API exposes this skill’s revision ID.</p>{/if}</div></div><div class="mt-3 flex flex-wrap justify-end gap-2"><button aria-label={`${item.enabled?'Disable':'Enable'} ${item.name}`} title={!item.revision_id?'Revision ID unavailable':undefined} class="inline-flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-xs disabled:opacity-50" disabled={busy===item.id || !item.revision_id} onclick={()=>update(item,!item.enabled,!item.enabled)}>{#if item.enabled}<ToggleRight size={17} class="text-[var(--accent)]"/>Enabled · revision pinned{:else}<ToggleLeft size={17}/>Enable pinned revision{/if}</button></div></article>{/each}</div>{/if}
 </div>
</section>
