<script lang="ts">
 import { onMount } from 'svelte';
 import { Settings, FolderKey } from 'lucide-svelte';
 import { DEFAULT_PROJECT_ID, readProjectScope, writeProjectScope } from '$lib/project-scope';
 import WorkspaceInstructions from '$lib/components/settings/WorkspaceInstructions.svelte';
 import SkillsCatalog from '$lib/components/settings/SkillsCatalog.svelte';
 import CapabilityInventory from '$lib/components/settings/CapabilityInventory.svelte';
 import MCPIntegrations from '$lib/components/MCPIntegrations.svelte';
 let projectId=$state(DEFAULT_PROJECT_ID);
 let scopeReady=$state(false);
 onMount(()=>{projectId=readProjectScope();scopeReady=true;});
 $effect(()=>{if(scopeReady) writeProjectScope(projectId);});
</script>
<svelte:head><title>Project Settings · Archon</title></svelte:head>
<div class="mx-auto min-w-0 max-w-5xl space-y-5 overflow-x-clip p-4 sm:p-6">
 <header class="flex items-start gap-3"><div class="grid size-11 shrink-0 place-items-center rounded-xl bg-[var(--raised)]"><Settings size={20} class="text-[var(--accent)]"/></div><div><p class="eyebrow">Progressive project configuration</p><h1 class="mt-1 text-xl font-semibold">Settings</h1><p class="mt-1 text-xs leading-5 text-[var(--muted)]">Instructions, reviewed skills, MCP integrations, and governed execution capabilities.</p></div></header>
 <section class="sticky top-0 z-10 rounded-xl border border-[rgba(85,214,190,.3)] bg-[rgba(16,21,29,.96)] p-3 backdrop-blur" aria-label="Active project scope"><label for="project-scope" class="flex flex-col gap-2 text-xs font-semibold text-[var(--secondary)] sm:flex-row sm:items-center"><span class="flex items-center gap-2"><FolderKey size={16} class="text-[var(--accent)]"/>Project scope</span><input id="project-scope" bind:value={projectId} class="min-h-11 min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 font-mono text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]" aria-describedby="scope-help"/><span id="scope-help" class="font-normal text-[var(--muted)]">All controls below apply only here.</span></label></section>
 <nav aria-label="Settings sections" class="grid grid-cols-2 gap-1 rounded-xl border border-[var(--border)] bg-[var(--panel)] p-1 text-center text-xs sm:grid-cols-4"><a href="#workspace" class="flex min-h-11 items-center justify-center rounded-lg px-2 text-[var(--secondary)] no-underline hover:bg-[var(--raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]">Workspace</a><a href="#skills" class="flex min-h-11 items-center justify-center rounded-lg px-2 text-[var(--secondary)] no-underline hover:bg-[var(--raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]">Skills</a><a href="#mcp" class="flex min-h-11 items-center justify-center rounded-lg px-2 text-[var(--secondary)] no-underline hover:bg-[var(--raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]">MCP</a><a href="#capabilities" class="flex min-h-11 items-center justify-center rounded-lg px-2 text-[var(--secondary)] no-underline hover:bg-[var(--raised)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]">Capabilities</a></nav>
 {#if projectId.trim()}<WorkspaceInstructions projectId={projectId.trim()}/><SkillsCatalog projectId={projectId.trim()}/><MCPIntegrations projectId={projectId.trim()}/><CapabilityInventory projectId={projectId.trim()}/>{:else}<div class="rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted)]">Enter a project scope to load settings.</div>{/if}
</div>
