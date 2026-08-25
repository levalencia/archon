<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
    import { Settings, Package, GitBranch, Trash2, Plus, Save, Check } from 'lucide-svelte';

  let skillsTopK = $state(3);
  let loading = $state(false);
  let saved = $state(false);
  let skills: any[] = $state([]);
  let importRepo = $state('');
  let importPath = $state('SKILL.md');
  let importStatus = $state('');
  let importLoading = $state(false);

  async function loadSettings() {
    try {
      const sr = await authenticatedFetch('/api/skills');
      if (sr.ok) skills = await sr.json();
    } catch { /* ignore */ }
  }

  async function saveSettings() {
    loading = true;
    try {
      await authenticatedFetch('/api/skills', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ top_k: skillsTopK }),
      });
      saved = true;
      setTimeout(() => saved = false, 2000);
    } catch { /* ignore */ }
    loading = false;
  }

  async function importSkill() {
    if (!importRepo) return;
    importLoading = true;
    importStatus = 'Importing…';
    try {
      const r = await authenticatedFetch('/api/skills/import/github', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo: importRepo, path: importPath }),
      });
      const d = await r.json();
      importStatus = d.error ? `Error: ${d.error}` : `Imported: ${d.name} (${d.content_length} chars)`;
      importRepo = '';
      await loadSettings();
    } catch {
      importStatus = 'Import failed — check repo path';
    }
    importLoading = false;
  }

  async function deleteSkill(id: string) {
    await authenticatedFetch(`/api/skills/${id}`, { method: 'DELETE' });
    await loadSettings();
  }

  $effect(() => { loadSettings(); });
</script>

<div class="max-w-4xl mx-auto p-6 space-y-6">
  <!-- Page header -->
  <div class="flex items-center gap-3">
    <div class="p-2 rounded-lg bg-[var(--bg-tertiary)]">
      <Settings size={20} class="text-[var(--accent)]" />
    </div>
    <div>
      <h1 class="text-xl font-semibold text-[var(--text-primary)]">Settings</h1>
      <p class="text-xs text-[var(--text-muted)]">Skills configuration & management</p>
    </div>
  </div>

  <!-- Skills Configuration -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center gap-2 mb-5">
      <Package size={16} class="text-[var(--accent)]" />
      <h2 class="text-base font-semibold text-[var(--text-primary)]">Skills Configuration</h2>
    </div>

    <!-- Top-K Slider -->
    <div class="mb-5">
      <label for="skills-top-k" class="block text-sm text-[var(--text-secondary)] mb-2">
        Skills per query (top K): <span class="font-semibold text-[var(--accent)]">{skillsTopK}</span>
      </label>
      <div class="flex items-center gap-4">
        <input
          id="skills-top-k"
          type="range"
          bind:value={skillsTopK}
          min="1" max="10" step="1"
          class="flex-1 h-2 rounded-full appearance-none cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
            [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--accent)]
            [&::-webkit-slider-thumb]:shadow-[0_0_8px_var(--accent-glow)]
            [&::-webkit-slider-runnable-track]:bg-[var(--bg-tertiary)] [&::-webkit-slider-runnable-track]:rounded-full"
        />
        <span class="text-xs text-[var(--text-muted)] w-8 text-right">{skillsTopK}/10</span>
      </div>
    </div>

    <button
      onclick={saveSettings}
      disabled={loading}
      class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer
        {saved
          ? 'bg-[rgba(63,185,80,0.15)] text-[var(--success)] border border-[var(--success)]'
          : 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]'}"
    >
      {#if saved}
        <Check size={14} />
        Saved
      {:else}
        <Save size={14} />
        {loading ? 'Saving…' : 'Save Settings'}
      {/if}
    </button>
  </section>

  <!-- Import from GitHub -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center gap-2 mb-4">
      <GitBranch size={16} class="text-[var(--text-secondary)]" />
      <h2 class="text-base font-semibold text-[var(--text-primary)]">Import from GitHub</h2>
    </div>

    <div class="flex gap-2">
      <input
        type="text"
        bind:value={importRepo}
        placeholder="owner/repo (e.g. mattpocock/skills)"
        class="flex-1 px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg
          text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)] transition-colors"
      />
      <input
        type="text"
        bind:value={importPath}
        placeholder="path/to/SKILL.md"
        class="w-48 px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg
          text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)] transition-colors"
      />
      <button
        onclick={importSkill}
        disabled={importLoading || !importRepo}
        class="inline-flex items-center gap-1.5 px-4 py-2 bg-[var(--bg-tertiary)] border border-[var(--border)]
          rounded-lg text-[var(--text-primary)] text-sm hover:border-[var(--accent)] transition-colors cursor-pointer
          disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Plus size={14} />
        {importLoading ? 'Importing…' : 'Import'}
      </button>
    </div>
    {#if importStatus}
      <p class="text-xs mt-2 {importStatus.startsWith('Error') ? 'text-[var(--error)]' : 'text-[var(--success)]'}">
        {importStatus}
      </p>
    {/if}
  </section>

  <!-- Skills List -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <Package size={16} class="text-[var(--purple)]" />
        <h2 class="text-base font-semibold text-[var(--text-primary)]">
          Registered Skills
        </h2>
        <span class="text-xs px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
          {skills.length}
        </span>
      </div>
    </div>

    {#if skills.length === 0}
      <div class="text-center py-8 text-[var(--text-muted)]">
        <Package size={32} class="mx-auto mb-2 opacity-40" />
        <p class="text-sm">No skills registered yet</p>
        <p class="text-xs mt-1">Import one from GitHub above</p>
      </div>
    {:else}
      <div class="space-y-2">
        {#each skills as skill}
          <div class="flex items-center justify-between px-4 py-3 bg-[var(--bg-tertiary)] rounded-lg
            border border-transparent hover:border-[var(--border)] transition-colors group">
            <div class="flex items-center gap-3">
              <Package size={14} class="text-[var(--text-muted)]" />
              <div>
                <span class="text-sm font-medium text-[var(--text-primary)]">{skill.name}</span>
                <span class="text-xs text-[var(--text-muted)] ml-2">{skill.content_length} chars</span>
                {#if skill.source_url}
                  <span class="inline-flex items-center gap-1 text-[10px] text-[var(--accent)] ml-2">
                    <GitBranch size={10} /> GitHub
                  </span>
                {:else}
                  <span class="text-[10px] text-[var(--text-muted)] ml-2">built-in</span>
                {/if}
              </div>
            </div>
            <button
              onclick={() => deleteSkill(skill.id || skill.name)}
              class="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--error)]
                hover:bg-[rgba(248,81,73,0.1)] transition-colors cursor-pointer
                opacity-0 group-hover:opacity-100"
              title="Delete skill"
            >
              <Trash2 size={14} />
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>
</div>
