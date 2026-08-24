<script lang="ts">
 import type { Artifact } from '$lib/types';
 import { authenticatedFetch } from '$lib/auth';
 let { artifacts = [], onClose = () => {} }: { artifacts?: Artifact[]; onClose?: () => void } = $props();
 let selected = $state('');
 let preview = $state('');
 $effect(() => { if (artifacts.length && !artifacts.some(a => a.id === selected)) selected = artifacts[0].id; });
 $effect(() => {
   const artifactId = selected;
   preview = '';
   if (!artifactId) return;
   authenticatedFetch(`/api/artifacts/${artifactId}/render`)
     .then((response) => response.ok ? response.text() : '<p>Artifact unavailable</p>')
     .then((content) => { if (selected === artifactId) preview = content; });
 });
</script>
<div class="artifact-backdrop" role="presentation" onclick={(e) => { if (e.currentTarget === e.target) onClose(); }}>
 <aside class="artifact-panel" aria-label="Artifact preview"><header><div><p class="eyebrow">Evidence</p><h2>Artifact preview</h2></div><button class="icon-button" aria-label="Close artifact preview" onclick={onClose}>×</button></header>
 {#if artifacts.length > 1}<div class="artifact-tabs">{#each artifacts as art}<button class:active={selected === art.id} onclick={() => selected = art.id}>{art.title}</button>{/each}</div>{/if}
 {#if selected}<iframe srcdoc={preview} title="Artifact preview" sandbox=""></iframe>{/if}
 </aside>
</div>
<svelte:window onkeydown={(e) => { if (e.key === 'Escape') onClose(); }} />
