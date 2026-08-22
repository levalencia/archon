<script lang="ts">
  interface TraceEntry {
    name: string;
    type: 'llm' | 'tool' | 'security' | 'error';
    meta: string[];
    barStart: number;
    barWidth: number;
  }

  interface Stats {
    latency: string;
    tokens: string;
    tools: number;
    iterations: number;
  }

  let { stats = { latency: '—', tokens: '—', tools: 0, iterations: 0 }, correlationId = '', traces = [] as TraceEntry[] }: {
    stats?: Stats;
    correlationId?: string;
    traces?: TraceEntry[];
  } = $props();

  let activeTab = $state('trace');

  const borderColors: Record<string, string> = {
    llm: 'border-l-[var(--accent)]',
    tool: 'border-l-[var(--success)]',
    security: 'border-l-[var(--warning)]',
    error: 'border-l-[var(--error)]',
  };

  const bgColors: Record<string, string> = {
    llm: 'bg-[rgba(88,166,255,0.05)]',
    tool: 'bg-[rgba(63,185,80,0.05)]',
    security: 'bg-[rgba(210,153,34,0.05)]',
    error: 'bg-[rgba(248,81,73,0.05)]',
  };

  const barColors: Record<string, string> = {
    llm: 'bg-[var(--accent)]',
    tool: 'bg-[var(--success)]',
    security: 'bg-[var(--warning)]',
    error: 'bg-[var(--error)]',
  };
</script>

<aside class="w-[340px] bg-[var(--bg-secondary)] border-l border-[var(--border)] flex flex-col shrink-0">
  <!-- Tabs -->
  <div class="px-4 py-3 border-b border-[var(--border)] flex items-center gap-2">
    {#each ['trace', 'audit', 'metrics'] as tab}
      <button
        onclick={() => activeTab = tab}
        class="px-3 py-1.5 rounded-md text-xs cursor-pointer transition-all capitalize
          {activeTab === tab
            ? 'bg-[var(--accent-glow)] text-[var(--accent)]'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'}"
      >
        {tab}
      </button>
    {/each}
  </div>

  <div class="flex-1 overflow-y-auto p-3">
    {#if activeTab === 'trace'}
      <!-- Stats grid -->
      <div class="grid grid-cols-2 gap-2 mb-3">
        <div class="p-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md">
          <div class="text-[11px] text-[var(--text-muted)] mb-1">Latency</div>
          <div class="text-lg font-semibold text-[var(--text-primary)]">{stats.latency}</div>
        </div>
        <div class="p-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md">
          <div class="text-[11px] text-[var(--text-muted)] mb-1">Tokens</div>
          <div class="text-lg font-semibold text-[var(--text-primary)]">{stats.tokens}</div>
        </div>
        <div class="p-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md">
          <div class="text-[11px] text-[var(--text-muted)] mb-1">Tools</div>
          <div class="text-lg font-semibold text-[var(--success)]">{stats.tools}</div>
        </div>
        <div class="p-2.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md">
          <div class="text-[11px] text-[var(--text-muted)] mb-1">Iterations</div>
          <div class="text-lg font-semibold text-[var(--text-primary)]">{stats.iterations}</div>
        </div>
      </div>

      <!-- Trace waterfall -->
      <div class="text-[11px] text-[var(--text-muted)] font-semibold mb-2">TRACE WATERFALL</div>

      {#each traces as trace}
        <div class="px-2.5 py-2 rounded-md mb-1 text-xs border-l-[3px] {borderColors[trace.type]} {bgColors[trace.type]}">
          <div class="font-medium text-[var(--text-primary)] mb-0.5">{trace.name}</div>
          <div class="text-[var(--text-muted)] font-mono text-[11px] flex gap-2">
            {#each trace.meta as m}
              <span>{m}</span>
            {/each}
          </div>
          <div class="h-1 rounded-sm mt-1 bg-[var(--border)] relative overflow-hidden">
            <div
              class="h-full rounded-sm absolute {barColors[trace.type]}"
              style="left: {trace.barStart}%; width: {trace.barWidth}%;"
            ></div>
          </div>
        </div>
      {/each}

      <!-- Correlation ID -->
      {#if correlationId}
        <div class="mt-4 text-[11px] text-[var(--text-muted)] font-semibold">CORRELATION ID</div>
        <div class="mt-1 px-2 py-1.5 bg-[var(--bg-tertiary)] rounded text-[11px] font-mono text-[var(--text-secondary)]">
          {correlationId}
        </div>
      {/if}

      <!-- Circuit breakers -->
      <div class="mt-4 text-[11px] text-[var(--text-muted)] font-semibold">CIRCUIT BREAKERS</div>
      <div class="mt-1.5 space-y-1">
        <div class="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <span class="w-2 h-2 rounded-full bg-[var(--success)]"></span>
          LLM Provider — CLOSED
        </div>
        <div class="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
          <span class="w-2 h-2 rounded-full bg-[var(--success)]"></span>
          Vector DB — CLOSED
        </div>
      </div>
    {/if}

    {#if activeTab === 'audit'}
      <div class="text-sm text-[var(--text-muted)] text-center py-8">
        Audit log will show here
      </div>
    {/if}

    {#if activeTab === 'metrics'}
      <div class="text-sm text-[var(--text-muted)] text-center py-8">
        Metrics dashboard will show here
      </div>
    {/if}
  </div>
</aside>
