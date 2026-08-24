<script lang="ts">
  let skillsTopK = $state(3);
  let loading = $state(false);
  let saved = $state(false);
  let skills: any[] = $state([]);
  let importRepo = $state('');
  let importPath = $state('SKILL.md');
  let importStatus = $state('');
  let metrics: any = $state(null);

  async function loadSettings() {
    const r = await fetch('/api/admin/settings');
    const d = await r.json();
    skillsTopK = d.settings?.skills_top_k || 3;

    const sr = await fetch('/api/skills');
    skills = await sr.json();

    const mr = await fetch('/api/admin/metrics');
    metrics = await mr.json();
  }

  async function saveSettings() {
    loading = true;
    await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skills_top_k: skillsTopK }),
    });
    saved = true;
    loading = false;
    setTimeout(() => saved = false, 2000);
  }

  async function importSkill() {
    if (!importRepo) return;
    importStatus = 'importing...';
    const r = await fetch('/api/skills/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: importRepo, path: importPath }),
    });
    const d = await r.json();
    importStatus = d.error ? `Error: ${d.error}` : `Imported: ${d.name} (${d.content_length} chars)`;
    importRepo = '';
    const sr = await fetch('/api/skills');
    skills = await sr.json();
  }

  async function deleteSkill(name: string) {
    await fetch(`/api/skills/${name}`, { method: 'DELETE' });
    const sr = await fetch('/api/skills');
    skills = await sr.json();
  }

  $effect(() => { loadSettings(); });
</script>

<div class="max-w-4xl mx-auto p-6">
  <h1 class="text-xl font-semibold text-[var(--text-primary)] mb-6">⚙️ Settings</h1>

  <!-- Skills Settings -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">Skills Configuration</h2>

    <div class="flex items-center gap-4 mb-4">
      <label for="skills-top-k" class="text-sm text-[var(--text-secondary)]">Skills per query (top K):</label>
      <input
        id="skills-top-k"
        type="number"
        bind:value={skillsTopK}
        min="1" max="10"
        class="w-20 px-3 py-1.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm"
      />
      <button
        onclick={saveSettings}
        disabled={loading}
        class="px-4 py-1.5 bg-[var(--accent)] text-white rounded-lg text-sm hover:bg-[var(--accent-hover)] cursor-pointer"
      >
        {saved ? '✓ Saved' : 'Save'}
      </button>
    </div>

    <!-- Import from GitHub -->
    <div class="border-t border-[var(--border)] pt-4 mt-4">
      <h3 class="text-sm font-medium text-[var(--text-primary)] mb-3">Import Skill from GitHub</h3>
      <div class="flex gap-2">
        <input
          type="text"
          bind:value={importRepo}
          placeholder="owner/repo (e.g. mattpocock/skills)"
          class="flex-1 px-3 py-1.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm"
        />
        <input
          type="text"
          bind:value={importPath}
          placeholder="path/to/SKILL.md"
          class="w-48 px-3 py-1.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm"
        />
        <button
          onclick={importSkill}
          class="px-4 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm hover:border-[var(--accent)] cursor-pointer"
        >
          Import
        </button>
      </div>
      {#if importStatus}
        <p class="text-xs text-[var(--text-muted)] mt-2">{importStatus}</p>
      {/if}
    </div>

    <!-- Skills list -->
    <div class="border-t border-[var(--border)] pt-4 mt-4">
      <h3 class="text-sm font-medium text-[var(--text-primary)] mb-3">
        Registered Skills ({skills.length})
      </h3>
      <div class="space-y-2">
        {#each skills as skill}
          <div class="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] rounded-lg">
            <div>
              <span class="text-sm text-[var(--text-primary)]">{skill.name}</span>
              <span class="text-xs text-[var(--text-muted)] ml-2">{skill.content_length} chars</span>
              {#if skill.source_url}
                <span class="text-[10px] text-[var(--accent)] ml-2">GitHub</span>
              {:else}
                <span class="text-[10px] text-[var(--text-muted)] ml-2">built-in</span>
              {/if}
            </div>
            <button
              onclick={() => deleteSkill(skill.name)}
              class="text-xs text-[var(--text-muted)] hover:text-[var(--error)] cursor-pointer"
            >
              ✕
            </button>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <!-- Metrics -->
  {#if metrics}
    <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
      <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">📊 Metrics</h2>
      <div class="grid grid-cols-4 gap-3">
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Uptime</div>
          <div class="text-lg font-semibold text-[var(--text-primary)]">
            {Math.round((metrics.uptime_seconds || 0) / 60)}m
          </div>
        </div>
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Circuit Breakers</div>
          <div class="text-lg font-semibold text-[var(--success)]">
            {metrics.circuit_breaker_count || 0}
          </div>
        </div>
      </div>
    </section>
  {/if}
</div>
