<script lang="ts">
  interface ArtifactSummary {
    id: string;
    title: string;
    type: string;
    language: string;
    content_length: number;
    version: number;
  }

  let { artifacts = [], onClose = () => {} }: {
    artifacts?: ArtifactSummary[];
    onClose?: () => void;
  } = $props();

  let selectedId = $state('');
  let renderUrl = $state('');

  const typeIcons: Record<string, string> = {
    html: '🌐',
    code: '💻',
    svg: '🎨',
    mermaid: '📊',
    markdown: '📝',
    csv: '📋',
    json: '🔧',
  };

  function selectArtifact(id: string) {
    selectedId = id;
    renderUrl = `/api/artifacts/${id}/render`;
  }

  // Auto-select first artifact
  $effect(() => {
    if (artifacts.length > 0 && !selectedId) {
      selectArtifact(artifacts[0].id);
    }
  });
</script>

{#if artifacts.length > 0}
  <aside class="w-[480px] bg-[var(--bg-secondary)] border-l border-[var(--border)] flex flex-col shrink-0">
    <!-- Header -->
    <div class="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="text-sm">📦</span>
        <span class="text-sm font-semibold text-[var(--text-primary)]">Artifacts</span>
        <span class="text-[11px] text-[var(--text-muted)] bg-[var(--bg-tertiary)] px-1.5 py-0.5 rounded">
          {artifacts.length}
        </span>
      </div>
      <button
        onclick={onClose}
        class="text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer text-sm"
      >
        ✕
      </button>
    </div>

    <!-- Artifact tabs (if multiple) -->
    {#if artifacts.length > 1}
      <div class="px-3 py-2 border-b border-[var(--border)] flex gap-1 overflow-x-auto">
        {#each artifacts as art}
          <button
            onclick={() => selectArtifact(art.id)}
            class="px-3 py-1.5 rounded-md text-xs cursor-pointer whitespace-nowrap flex items-center gap-1.5 transition-all
              {selectedId === art.id
                ? 'bg-[var(--accent-glow)] text-[var(--accent)] border border-[rgba(88,166,255,0.2)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] border border-transparent'}"
          >
            <span>{typeIcons[art.type] || '📄'}</span>
            <span>{art.title}</span>
          </button>
        {/each}
      </div>
    {/if}

    <!-- Artifact info bar -->
    {#if selectedId}
      {@const selected = artifacts.find(a => a.id === selectedId)}
      {#if selected}
        <div class="px-4 py-2 border-b border-[var(--border)] flex items-center gap-3 text-[11px] text-[var(--text-muted)]">
          <span class="text-base">{typeIcons[selected.type] || '📄'}</span>
          <span class="font-medium text-[var(--text-secondary)]">{selected.title}</span>
          <span class="font-mono">{selected.language}</span>
          <span>{Math.round(selected.content_length / 1024 * 10) / 10}KB</span>
          <span>v{selected.version}</span>
        </div>
      {/if}
    {/if}

    <!-- Render area -->
    <div class="flex-1 overflow-hidden">
      {#if renderUrl}
        <iframe
          src={renderUrl}
          title="Artifact preview"
          class="w-full h-full border-none bg-[var(--bg-primary)]"
          sandbox="allow-scripts allow-same-origin"
        ></iframe>
      {:else}
        <div class="flex items-center justify-center h-full text-[var(--text-muted)] text-sm">
          Select an artifact to preview
        </div>
      {/if}
    </div>
  </aside>
{/if}
