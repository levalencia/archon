<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  let memoryStats: any = $state(null);
  let contextStats: any = $state(null);
  let checkpoints: any[] = $state([]);
  let selectedConvId = $state('');

  async function loadMemory() {
    try {
      const r = await authenticatedFetch('/api/admin/health');
      memoryStats = await r.json();
    } catch { memoryStats = { error: 'Cannot connect' }; }
  }

  $effect(() => { loadMemory(); });
</script>

<div class="max-w-4xl mx-auto p-6">
  <h1 class="text-xl font-semibold text-[var(--text-primary)] mb-6">🧠 Memory Inspector</h1>

  <!-- Memory Tiers -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">Memory Tiers</h2>
    <div class="grid grid-cols-3 gap-4">
      <div class="p-4 bg-[var(--bg-tertiary)] rounded-lg border-l-4 border-l-[var(--error)]">
        <div class="text-sm font-semibold text-[var(--text-primary)] mb-1">🔥 Hot (Redis)</div>
        <div class="text-xs text-[var(--text-muted)]">Current conversation context</div>
        <div class="text-xs text-[var(--text-muted)] mt-1">Last N messages, 24h TTL</div>
        <div class="mt-2 text-lg font-bold text-[var(--error)]">Active</div>
      </div>
      <div class="p-4 bg-[var(--bg-tertiary)] rounded-lg border-l-4 border-l-[var(--warning)]">
        <div class="text-sm font-semibold text-[var(--text-primary)] mb-1">📦 Warm (PostgreSQL)</div>
        <div class="text-xs text-[var(--text-muted)]">Summarized history, searchable</div>
        <div class="text-xs text-[var(--text-muted)] mt-1">Encrypted, indexed</div>
        <div class="mt-2 text-lg font-bold text-[var(--warning)]">Persistent</div>
      </div>
      <div class="p-4 bg-[var(--bg-tertiary)] rounded-lg border-l-4 border-l-[var(--accent)]">
        <div class="text-sm font-semibold text-[var(--text-primary)] mb-1">❄️ Cold (Archive)</div>
        <div class="text-xs text-[var(--text-muted)]">Full encrypted archives</div>
        <div class="text-xs text-[var(--text-muted)] mt-1">Compressed, blob storage</div>
        <div class="mt-2 text-lg font-bold text-[var(--accent)]">Archived</div>
      </div>
    </div>
  </section>

  <!-- Context Window -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">Context Window</h2>
    <div class="flex items-center gap-4">
      <div class="flex-1 h-4 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
        <div class="h-full bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] rounded-full" style="width: 45%"></div>
      </div>
      <span class="text-xs text-[var(--text-muted)]">~45% used (1,840 / 4,096 tokens)</span>
    </div>
    <div class="flex gap-4 mt-3 text-xs text-[var(--text-muted)]">
      <span>System prompt: 320 tokens</span>
      <span>History: 1,200 tokens</span>
      <span>Tools: 320 tokens</span>
      <span>Reserved: 2,256 tokens</span>
    </div>
  </section>

  <!-- Checkpoints -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">💾 Checkpoints</h2>
    <div class="text-sm text-[var(--text-muted)]">
      State checkpoints allow restoring a conversation to any saved point.
      Checkpoints are created automatically every 10 messages.
    </div>
  </section>
</div>
