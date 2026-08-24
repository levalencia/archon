<script lang="ts">
 import type { Artifact } from '$lib/types';
 let { artifacts = [], onClose = () => {} }: { artifacts?: Artifact[]; onClose?: () => void } = $props(); let selected = $state('');
 $effect(() => { if (artifacts.length && !artifacts.some(a => a.id === selected)) selected = artifacts[0].id; });
</script>
<div class="artifact-backdrop" role="presentation" onclick={(e) => { if (e.currentTarget === e.target) onClose(); }}>
 <aside class="artifact-panel" aria-label="Artifact preview"><header><div><p class="eyebrow">Evidence</p><h2>Artifact preview</h2></div><button class="icon-button" aria-label="Close artifact preview" onclick={onClose}>×</button></header>
 {#if artifacts.length > 1}<div class="artifact-tabs">{#each artifacts as art}<button class:active={selected === art.id} onclick={() => selected = art.id}>{art.title}</button>{/each}</div>{/if}
 {#if selected}<iframe src={`/api/artifacts/${selected}/render`} title="Artifact preview" sandbox="allow-scripts allow-same-origin"></iframe>{/if}
 </aside>
</div>
<svelte:window onkeydown={(e) => { if (e.key === 'Escape') onClose(); }} />
