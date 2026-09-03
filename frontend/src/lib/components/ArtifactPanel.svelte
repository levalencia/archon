<script lang="ts">
  import type { Artifact } from '$lib/types';
  import { authenticatedFetch } from '$lib/auth';
  import { buildArtifactPreview } from '$lib/artifact-preview';

  let {
    artifacts = [],
    onClose = () => {},
  }: { artifacts?: Artifact[]; onClose?: () => void } = $props();
  let selected = $state('');
  let preview = $state('');
  let loading = $state(false);
  let error = $state('');

  $effect(() => {
    if (artifacts.length && !artifacts.some((artifact) => artifact.id === selected)) {
      selected = artifacts[0].id;
    }
  });

  $effect(() => {
    const artifactId = selected;
    const artifact = artifacts.find((item) => item.id === artifactId);
    let cancelled = false;
    preview = '';
    error = '';
    loading = false;
    if (!artifact) return;

    if (artifact.content) {
      preview = buildArtifactPreview(artifact);
      return;
    }

    loading = true;
    const url = artifact.type === 'html'
      ? `/api/artifacts/${artifactId}`
      : `/api/artifacts/${artifactId}/render`;
    authenticatedFetch(url)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Artifact unavailable (${response.status})`);
        if (artifact.type === 'html') {
          const stored = await response.json() as Artifact;
          return buildArtifactPreview(stored);
        }
        return response.text();
      })
      .then((content) => {
        if (!cancelled && selected === artifactId) preview = content;
      })
      .catch((reason: unknown) => {
        if (!cancelled && selected === artifactId) {
          error = reason instanceof Error ? reason.message : 'Artifact unavailable';
        }
      })
      .finally(() => {
        if (!cancelled && selected === artifactId) loading = false;
      });

    return () => { cancelled = true; };
  });
</script>

<div class="artifact-backdrop" role="presentation" onclick={(event) => { if (event.currentTarget === event.target) onClose(); }}>
  <aside class="artifact-panel" aria-label="Artifact preview">
    <header>
      <div><p class="eyebrow">Evidence</p><h2>Artifact preview</h2></div>
      <button class="icon-button" aria-label="Close artifact preview" onclick={onClose}>×</button>
    </header>
    {#if artifacts.length > 1}
      <div class="artifact-tabs">
        {#each artifacts as artifact}
          <button class:active={selected === artifact.id} onclick={() => selected = artifact.id}>{artifact.title}</button>
        {/each}
      </div>
    {/if}
    {#if loading}
      <p class="status" role="status">Loading artifact…</p>
    {:else if error}
      <p class="status error" role="alert">{error}</p>
    {:else if preview}
      {#key preview}
        <iframe srcdoc={preview} title="Artifact preview" sandbox="" referrerpolicy="no-referrer"></iframe>
      {/key}
    {/if}
  </aside>
</div>
<svelte:window onkeydown={(event) => { if (event.key === 'Escape') onClose(); }} />
