<script lang="ts">
  let evalResults: any = $state(null);
  let redTeamResults: any = $state(null);
  let fuzzResults: any = $state(null);
  let running = $state('');

  async function runRedTeam() {
    running = 'redteam';
    const r = await fetch('/api/security/red-team', { method: 'POST' });
    redTeamResults = await r.json();
    running = '';
  }

  async function runFuzz() {
    running = 'fuzz';
    const r = await fetch('/api/security/fuzz', { method: 'POST' });
    fuzzResults = await r.json();
    running = '';
  }
</script>

<div class="max-w-5xl mx-auto p-6">
  <h1 class="text-xl font-semibold text-[var(--text-primary)] mb-6">🧪 Evaluation & Security</h1>

  <!-- Red Team -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-base font-semibold text-[var(--text-primary)]">🔴 Red Team Testing</h2>
      <button onclick={runRedTeam} disabled={running === 'redteam'}
        class="px-4 py-1.5 bg-[var(--error)] text-white rounded-lg text-sm cursor-pointer hover:opacity-90 disabled:opacity-50">
        {running === 'redteam' ? 'Running...' : 'Run Red Team'}
      </button>
    </div>

    {#if redTeamResults}
      <div class="grid grid-cols-3 gap-3 mb-4">
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Total Prompts</div>
          <div class="text-xl font-bold text-[var(--text-primary)]">{redTeamResults.total_prompts}</div>
        </div>
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Blocked</div>
          <div class="text-xl font-bold text-[var(--success)]">{redTeamResults.blocked}</div>
        </div>
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Block Rate</div>
          <div class="text-xl font-bold {redTeamResults.block_rate >= 0.8 ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
            {Math.round(redTeamResults.block_rate * 100)}%
          </div>
        </div>
      </div>
      <div class="space-y-1 max-h-48 overflow-y-auto">
        {#each redTeamResults.results as r}
          <div class="flex items-center gap-2 px-3 py-1.5 text-xs {r.blocked ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
            <span>{r.blocked ? '🛡️' : '⚠️'}</span>
            <span class="text-[var(--text-secondary)] truncate flex-1">{r.prompt}</span>
            <span class="font-mono">{r.triggered_rules?.join(', ') || 'none'}</span>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <!-- Fuzz Testing -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-base font-semibold text-[var(--text-primary)]">🔀 Fuzz Testing</h2>
      <button onclick={runFuzz} disabled={running === 'fuzz'}
        class="px-4 py-1.5 bg-[var(--warning)] text-white rounded-lg text-sm cursor-pointer hover:opacity-90 disabled:opacity-50">
        {running === 'fuzz' ? 'Running...' : 'Run Fuzz (50 inputs)'}
      </button>
    </div>

    {#if fuzzResults}
      <div class="grid grid-cols-3 gap-3 mb-4">
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Total Inputs</div>
          <div class="text-xl font-bold text-[var(--text-primary)]">{fuzzResults.total_inputs}</div>
        </div>
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Crashes</div>
          <div class="text-xl font-bold {fuzzResults.crashes === 0 ? 'text-[var(--success)]' : 'text-[var(--error)]'}">
            {fuzzResults.crashes}
          </div>
        </div>
        <div class="p-3 bg-[var(--bg-tertiary)] rounded-lg">
          <div class="text-[11px] text-[var(--text-muted)]">Unexpected</div>
          <div class="text-xl font-bold text-[var(--warning)]">{fuzzResults.unexpected}</div>
        </div>
      </div>
    {/if}
  </section>
</div>
