<script lang="ts">
  import { ExternalLink } from 'lucide-svelte';
  import { githubSourceHref, sourceLabel, sourceWhy, type SourceReference } from '$lib/source-links';

  let {
    sources,
    sourceCommit,
    heading = 'Sources',
    compact = false,
  }: {
    sources: SourceReference[];
    sourceCommit: string;
    heading?: string;
    compact?: boolean;
  } = $props();
</script>

{#if sources.length}
  <section class:compact aria-label={heading}>
    <h5>{heading}</h5>
    <ul>
      {#each sources as source}
        <li>
          <a href={githubSourceHref(source, sourceCommit)} target="_blank" rel="noopener noreferrer">
            <span>{sourceLabel(source)}</span><ExternalLink size={13} aria-hidden="true" />
          </a>
          {#if sourceWhy(source)}<p>{sourceWhy(source)}</p>{/if}
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  section{margin-top:1rem;border-top:1px solid var(--border);padding-top:.85rem}h5{margin:0 0 .55rem;color:var(--secondary);font:700 .68rem var(--font-mono);letter-spacing:.08em;text-transform:uppercase}ul{display:grid;gap:.5rem;margin:0;padding:0;list-style:none}li{min-width:0}a{display:inline-flex;align-items:center;gap:.35rem;color:var(--accent);font-size:.78rem;font-weight:700;text-decoration:underline;text-decoration-color:color-mix(in srgb,var(--archon-orange) 45%,transparent);text-underline-offset:3px;overflow-wrap:anywhere}a:hover{text-decoration-color:currentColor}a:focus-visible{outline:2px solid var(--accent);outline-offset:3px;border-radius:.2rem;box-shadow:0 0 12px var(--archon-orange-glow)}p{margin:.25rem 0 0;color:var(--muted);font-size:.72rem;line-height:1.45}.compact{margin-top:.65rem;padding-top:.6rem}.compact h5{font-size:.62rem}.compact ul{gap:.3rem}
</style>
