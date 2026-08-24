<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';

  let { model = 'Claude Opus 4.6', provider = 'Foundry', showTrace = true, onToggleTrace = () => {} }: {
    model?: string;
    provider?: string;
    showTrace?: boolean;
    onToggleTrace?: () => void;
  } = $props();

  let healthStatus = $state<'healthy' | 'degraded' | 'down'>('healthy');
  let rateLimitInfo = $state('');

  async function checkHealth() {
    try {
      const r = await authenticatedFetch('/api/admin/health');
      if (r.ok) {
        healthStatus = 'healthy';
      } else {
        healthStatus = 'degraded';
      }
    } catch {
      healthStatus = 'down';
    }
  }

  $effect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  });

  const statusColors = {
    healthy: 'bg-[var(--success)]',
    degraded: 'bg-[var(--warning)]',
    down: 'bg-[var(--error)]',
  };
</script>

<div class="h-[52px] border-b border-[var(--border)] flex items-center px-5 gap-3 bg-[var(--bg-secondary)]">
  <!-- Health indicator -->
  <div class="flex items-center gap-1.5" title="System: {healthStatus}">
    <div class="w-2 h-2 rounded-full {statusColors[healthStatus]}"></div>
  </div>

  <!-- Model selector -->
  <div class="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-md text-[var(--text-primary)] text-[13px] cursor-pointer">
    <div class="w-2 h-2 rounded-full bg-[var(--success)]"></div>
    {model} ({provider})
    <span class="text-[var(--text-muted)]">▾</span>
  </div>

  <div class="flex-1"></div>

  <!-- Nav links -->
  <a href="/documents" class="px-3 py-1.5 bg-transparent border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs cursor-pointer flex items-center gap-1 hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all no-underline">
    📄 Docs
  </a>

  <button
    onclick={onToggleTrace}
    class="px-3 py-1.5 border rounded-md text-xs cursor-pointer flex items-center gap-1 transition-all
      {showTrace
        ? 'bg-[var(--accent-glow)] border-[var(--accent)] text-[var(--accent)]'
        : 'bg-transparent border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}"
  >
    🔍 Trace
  </button>

  <a href="/eval" class="px-3 py-1.5 bg-transparent border border-[var(--border)] rounded-md text-[var(--text-secondary)] text-xs cursor-pointer flex items-center gap-1 hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-all no-underline">
    🛡️ Security
  </a>
</div>
