<script lang="ts">
  import { FileText, RefreshCw, ShieldCheck } from 'lucide-svelte';
  import { listProjectInstructions, scanProjectWorkspace, type ProjectInstruction } from '$lib/project-instructions';
  let { projectId }: { projectId: string } = $props();
  let instructions: ProjectInstruction[] = $state([]);
  let loading = $state(true); let scanning = $state(false); let error = $state('');
  async function load() { loading = true; error = ''; try { instructions = await listProjectInstructions(projectId); } catch (e) { error = e instanceof Error ? e.message : 'Instructions unavailable'; } finally { loading = false; } }
  async function scan() { scanning = true; error = ''; try { await scanProjectWorkspace(projectId); await load(); } catch (e) { error = e instanceof Error ? e.message : 'Workspace scan failed'; } finally { scanning = false; } }
  $effect(() => { projectId; queueMicrotask(() => void load()); });
  const shortHash = (hash: string) => hash.length > 14 ? `${hash.slice(0, 12)}…` : hash;
</script>
<section id="workspace" aria-labelledby="workspace-title" class="rounded-xl border border-[var(--border)] bg-[var(--panel)] p-4 sm:p-5">
  <header class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <div><p class="eyebrow">Project-scoped</p><h2 id="workspace-title" class="mt-1 text-base font-semibold">Workspace &amp; Instructions</h2><p class="mt-1 text-xs leading-5 text-[var(--muted)]">Trusted, versioned instruction files resolved from root to active scope.</p></div>
    <button class="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--raised)] px-3 text-sm hover:border-[var(--accent)] disabled:opacity-50" onclick={scan} disabled={scanning}><RefreshCw size={15} />{scanning ? 'Scanning…' : 'Scan workspace'}</button>
  </header>
  {#if loading}<div class="mt-4 rounded-lg border border-[var(--border)] p-5 text-sm text-[var(--muted)]" aria-live="polite">Loading instructions…</div>
  {:else if error}<div class="mt-4 rounded-lg border border-[rgba(255,107,114,.4)] bg-[rgba(255,107,114,.08)] p-4 text-sm text-[var(--danger)]" role="alert">{error}<button class="ml-2 text-[var(--accent)] underline" onclick={load}>Retry</button></div>
  {:else if !instructions.length}<div class="mt-4 rounded-lg border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--muted)]">No instruction revisions found for this project.</div>
  {:else}<div class="mt-4 space-y-2">{#each instructions as item (item.id)}<details class="rounded-lg border border-[var(--border)] bg-[var(--panel-2)]"><summary class="flex min-h-11 cursor-pointer list-none items-center gap-3 px-3 py-2"><FileText size={16} class="shrink-0 text-[var(--accent)]"/><span class="min-w-0 flex-1"><strong class="block truncate text-sm">{item.relative_path}</strong><small class="text-[var(--muted)]">Scope {item.scope_path} · rev {item.revision}</small></span><span class="rounded-full border border-[var(--border)] px-2 py-1 text-[10px] text-[var(--secondary)]">{item.trust_state}</span></summary><dl class="grid gap-2 border-t border-[var(--border)] p-3 text-xs sm:grid-cols-2"><div><dt class="text-[var(--muted)]">Content hash</dt><dd class="mt-1 font-mono" title={item.content_hash}>{shortHash(item.content_hash)}</dd></div><div><dt class="text-[var(--muted)]">Size</dt><dd class="mt-1">{item.byte_count.toLocaleString()} bytes</dd></div></dl></details>{/each}</div>{/if}
  <p class="mt-4 flex gap-2 text-xs text-[var(--muted)]"><ShieldCheck size={15} class="shrink-0"/>Instructions cannot grant tool permissions or override project policy.</p>
</section>
