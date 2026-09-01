<script lang="ts">

  import { Plug, Plus, RefreshCw, Trash2, AlertTriangle, ShieldCheck } from 'lucide-svelte';
  import {
    MCPApiError, createServer, deleteServer, discoverTools, listProfiles, listServers,
    listTools, toggleTool, updateServer, type MCPProfile, type MCPServer, type MCPTool,
  } from '$lib/mcp';

  let { projectId }: { projectId: string } = $props();
  let profiles: MCPProfile[] = $state([]);
  let servers: MCPServer[] = $state([]);
  let tools: Record<string, MCPTool[]> = $state({});
  let name = $state('');
  let profileId = $state('');
  let loading = $state(true);
  let busy = $state('');
  let error = $state('');

  function errorMessage(value: unknown): string {
    if (value instanceof MCPApiError) {
      if (value.status === 401) return 'Your session has expired. Sign in again to manage integrations.';
      if (value.status === 403 || value.status === 404) return 'This integration is unavailable or belongs to another owner.';
      if (value.code === 'unknown_profile') return 'That deployment profile is no longer available.';
      return `Request failed (${value.code}).`;
    }
    return 'MCP inventory is unavailable. Try again.';
  }

  async function load() {
    loading = true; error = '';
    try {
      profiles = await listProfiles();
      if (!profileId && profiles.length) profileId = profiles[0].id;
      servers = await listServers(projectId);
      const entries = await Promise.all(servers.map(async (server) => {
        try { return [server.id, await listTools(projectId, server.id)] as const; }
        catch { return [server.id, []] as const; }
      }));
      tools = Object.fromEntries(entries);
    } catch (value) { error = errorMessage(value); }
    finally { loading = false; }
  }

  async function create() {
    if (!name.trim() || !profileId) return;
    busy = 'create'; error = '';
    try {
      const server = await createServer(projectId, name.trim(), profileId);
      servers = [...servers, server]; tools[server.id] = []; name = '';
    } catch (value) { error = errorMessage(value); }
    finally { busy = ''; }
  }

  async function discover(server: MCPServer) {
    busy = `discover:${server.id}`; error = '';
    try {
      tools[server.id] = await discoverTools(projectId, server.id);
      await refreshServer(server.id);
    } catch (value) { error = errorMessage(value); }
    finally { busy = ''; }
  }

  async function refreshServer(id: string) {
    const refreshed = await listServers(projectId);
    servers = refreshed;
  }

  async function remove(server: MCPServer) {
    if (!confirm(`Delete ${server.name}? Discovered tool metadata will also be removed.`)) return;
    busy = `delete:${server.id}`; error = '';
    try { await deleteServer(projectId, server.id); servers = servers.filter((item) => item.id !== server.id); }
    catch (value) { error = errorMessage(value); }
    finally { busy = ''; }
  }

  async function setServerEnabled(server: MCPServer) {
    busy = `server:${server.id}`; error = '';
    try {
      const updated = await updateServer(projectId, server.id, { enabled: !server.enabled });
      servers = servers.map((item) => item.id === updated.id ? updated : item);
    } catch (value) { error = errorMessage(value); }
    finally { busy = ''; }
  }

  async function setToolEnabled(server: MCPServer, tool: MCPTool) {
    busy = `tool:${tool.id}`; error = '';
    try {
      const updated = await toggleTool(projectId, server.id, tool.name, !tool.enabled);
      tools[server.id] = (tools[server.id] ?? []).map((item) => item.id === updated.id ? updated : item);
    } catch (value) { error = errorMessage(value); }
    finally { busy = ''; }
  }

  const healthClass = (health: string) => health === 'healthy' ? 'text-[var(--success)]' :
    health === 'error' ? 'text-[var(--error)]' : 'text-[var(--text-muted)]';
  const seen = (date: string | null) => date ? new Date(date).toLocaleString() : 'Never';

  $effect(() => { projectId; queueMicrotask(() => void load()); });
</script>

<section id="mcp" aria-labelledby="mcp-heading" class="min-w-0 bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4 sm:p-5 space-y-5">
  <div class="flex items-start gap-3">
    <Plug size={18} class="text-[var(--accent)] mt-0.5" />
    <div>
      <h2 id="mcp-heading" class="text-base font-semibold text-[var(--text-primary)]">MCP integrations</h2>
      <p class="text-xs text-[var(--text-muted)]">Manage deployment-approved servers and their discovered tools. Tools cannot be called from this page.</p>
    </div>
  </div>

  <div class="grid sm:grid-cols-2 gap-2">
    <label class="text-xs text-[var(--text-muted)]">Integration name
      <input aria-label="Integration name" bind:value={name} placeholder="Documentation server" class="mt-1 min-h-11 w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)]" />
    </label>
    <label class="min-w-0 text-xs text-[var(--text-muted)]">Approved profile
      <select aria-label="Approved profile" bind:value={profileId} disabled={!profiles.length} class="mt-1 min-h-11 w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)]">
        {#if !profiles.length}<option value="">No profiles available</option>{/if}
        {#each profiles as profile}<option value={profile.id}>{profile.display_name}</option>{/each}
      </select>
    </label>
    <button onclick={create} disabled={busy === 'create' || !name.trim() || !profileId} class="sm:col-span-2 min-h-11 inline-flex justify-center items-center gap-2 px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm disabled:opacity-50">
      <Plus size={14} /> {busy === 'create' ? 'Creating…' : 'Add integration'}
    </button>
  </div>

  {#if error}<div role="alert" class="flex gap-2 p-3 rounded-lg bg-[rgba(248,81,73,.1)] text-[var(--error)] text-sm"><AlertTriangle size={16} />{error}</div>{/if}
  {#if loading}<p aria-live="polite" class="text-sm text-[var(--text-muted)]">Loading MCP inventory…</p>
  {:else if servers.length === 0}<div class="py-6 text-center text-sm text-[var(--text-muted)]">No MCP integrations for project “{projectId}”.</div>
  {:else}
    <div class="space-y-4">
      {#each servers as server (server.id)}
        <article data-testid="mcp-server" class="border border-[var(--border)] rounded-lg p-3 sm:p-4 space-y-4">
          <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2"><h3 class="font-medium text-[var(--text-primary)]">{server.name}</h3><span class="text-[10px] uppercase {healthClass(server.enabled ? server.health : 'disabled')}">{server.enabled ? server.health : 'disabled'}</span></div>
              <p class="text-xs text-[var(--text-muted)] mt-1">Profile: {server.profile_id} · Source: {server.transport} · Last seen: {seen(server.last_seen)}</p>
              {#if server.last_error_code}<p class="text-xs text-[var(--error)] mt-1">Error code: {server.last_error_code}</p>{/if}
            </div>
            <div class="flex flex-wrap gap-2">
              <button aria-label={`${server.enabled ? 'Disable' : 'Enable'} ${server.name}`} onclick={() => setServerEnabled(server)} disabled={busy === `server:${server.id}`} class="min-h-11 px-3 py-1.5 border border-[var(--border)] rounded-md text-xs text-[var(--text-secondary)]">{server.enabled ? 'Disable' : 'Enable'}</button>
              <button onclick={() => discover(server)} disabled={!server.enabled || busy === `discover:${server.id}`} class="min-h-11 inline-flex items-center gap-1 px-3 py-1.5 border border-[var(--border)] rounded-md text-xs text-[var(--text-secondary)]"><RefreshCw size={12}/>{busy === `discover:${server.id}` ? 'Discovering…' : 'Discover tools'}</button>
              <button aria-label={`Delete ${server.name}`} onclick={() => remove(server)} disabled={busy === `delete:${server.id}`} class="min-h-11 min-w-11 p-1.5 text-[var(--error)]"><Trash2 size={14}/></button>
            </div>
          </div>
          {#if (tools[server.id] ?? []).length === 0}<p class="text-xs text-[var(--text-muted)]">No tools discovered.</p>
          {:else}<div class="grid gap-2">
            {#each tools[server.id] as tool (tool.id)}
              <div data-testid="mcp-tool" class="flex flex-col sm:flex-row sm:items-start justify-between gap-3 bg-[var(--bg-tertiary)] rounded-lg p-3">
                <div class="min-w-0">
                  <div class="flex flex-wrap gap-2 items-center"><strong class="text-sm text-[var(--text-primary)]">{tool.title || tool.name}</strong><code class="text-[10px] text-[var(--text-muted)]">{tool.name}</code>{#if tool.read_only}<span class="text-[10px] text-[var(--success)]">read-only</span>{/if}{#if tool.destructive}<span class="text-[10px] text-[var(--error)]">destructive</span>{/if}</div>
                  {#if tool.description}<p class="text-xs text-[var(--text-muted)] mt-1">{tool.description}</p>{/if}
                  <details class="mt-2 min-w-0"><summary class="flex min-h-11 cursor-pointer items-center text-xs text-[var(--text-secondary)]">Input schema</summary><pre class="max-w-full overflow-auto text-[10px] mt-1 p-2 rounded bg-[var(--bg-primary)]">{JSON.stringify(tool.input_schema, null, 2)}</pre></details>
                </div>
                <label class="inline-flex min-h-11 items-center gap-2 text-xs text-[var(--text-secondary)]"><input class="size-5" type="checkbox" checked={tool.enabled} onchange={() => setToolEnabled(server, tool)} disabled={busy === `tool:${tool.id}`} /> Enabled</label>
              </div>
            {/each}
          </div>{/if}
        </article>
      {/each}
    </div>
  {/if}
  <div class="flex gap-2 text-xs text-[var(--text-muted)]"><ShieldCheck size={14}/> Profiles are administrator-approved. Commands, arguments, environment, and secrets are never shown or entered here.</div>
</section>
