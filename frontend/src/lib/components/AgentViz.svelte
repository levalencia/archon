<script lang="ts">
  interface AgentStep {
    agent: string;
    role: string;
    response: string;
    task: string;
    fallback?: boolean;
  }

  let { steps = [], agents = [] }: {
    steps?: AgentStep[];
    agents?: string[];
  } = $props();

  const agentColors: Record<string, string> = {
    planner: 'var(--accent)',
    retriever: 'var(--success)',
    validator: 'var(--warning)',
    synthesizer: 'var(--purple)',
    coordinator: 'var(--text-secondary)',
  };
</script>

{#if steps.length > 0}
  <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-4 mb-4">
    <div class="text-xs font-semibold text-[var(--text-muted)] mb-3">AGENT ORCHESTRATION</div>

    <!-- Pipeline visualization -->
    <div class="flex items-center gap-1 mb-4 overflow-x-auto pb-2">
      {#each agents as agent, i}
        {@const color = agentColors[agent] || 'var(--text-muted)'}
        <div class="flex items-center gap-1 shrink-0">
          <div
            class="px-3 py-1.5 rounded-lg text-xs font-medium border"
            style="border-color: {color}; color: {color}; background: {color}15;"
          >
            {agent}
          </div>
          {#if i < agents.length - 1}
            <span class="text-[var(--text-muted)] text-xs">→</span>
          {/if}
        </div>
      {/each}
    </div>

    <!-- Step details -->
    <div class="space-y-2">
      {#each steps as step, i}
        {@const color = agentColors[step.agent] || 'var(--text-muted)'}
        <div
          class="px-3 py-2 rounded-lg border-l-[3px]"
          style="border-left-color: {color}; background: {color}08;"
        >
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-semibold" style="color: {color};">
              {step.agent}
            </span>
            {#if step.fallback}
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-[rgba(248,81,73,0.15)] text-[var(--error)]">
                fallback
              </span>
            {/if}
            <span class="text-[10px] text-[var(--text-muted)]">
              {step.role}
            </span>
          </div>
          <div class="text-xs text-[var(--text-secondary)] line-clamp-2">
            {step.response?.substring(0, 200) || step.task?.substring(0, 200)}
          </div>
        </div>
      {/each}
    </div>
  </div>
{/if}
