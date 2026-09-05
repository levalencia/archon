<script lang="ts">
  import { onMount } from 'svelte';
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';
  type Segment = { chapter: string; text: string; speaker: string; sources?:SourceReference[] };
  let { title, mediaUrl, content, limitations, sourceCommit }: { title:string; mediaUrl:string; content:{segments:Segment[]}; limitations:string[]; sourceCommit:string }=$props();
  let captionsUrl = $state('data:text/vtt,WEBVTT%0A%0A');

  function stamp(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = (seconds % 60).toFixed(3).padStart(6, '0');
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${remainder}`;
  }

  onMount(() => {
    const sentences = content.segments.flatMap(segment => segment.text.match(/[^.!?]+[.!?]+/g) ?? [segment.text]);
    const cueLength = 70 / Math.max(sentences.length, 1);
    const cues = sentences.map((sentence, index) => `${index + 1}\n${stamp(index * cueLength)} --> ${stamp((index + 1) * cueLength)}\n${sentence.trim()}\n`).join('\n');
    captionsUrl = URL.createObjectURL(new Blob([`WEBVTT\n\n${cues}`], { type: 'text/vtt' }));
    return () => URL.revokeObjectURL(captionsUrl);
  });
</script>
<section class="video" aria-label="Video lesson player"><span class="eyebrow">English explainer video</span><h3>{title}</h3><video controls preload="metadata" src={mediaUrl} aria-describedby="video-transcript"><track kind="captions" src={captionsUrl} srclang="en" label="English" default/>Your browser does not support HTML video.</video><details id="video-transcript"><summary>Accessible transcript</summary>{#each content.segments as segment}<article><h4>{segment.chapter}</h4><p>{segment.text}</p>{#if segment.sources}<SourceLinks sources={segment.sources} {sourceCommit} compact />{/if}</article>{/each}</details><details><summary>What this does not prove</summary><ul>{#each limitations as item}<li>{item}</li>{/each}</ul></details></section>
<style>.video{border:1px solid var(--border);border-radius:1rem;background:var(--panel);padding:1rem}.video h3{font-size:1.5rem;margin:.5rem 0 1rem}.video video{display:block;width:100%;border-radius:.75rem;background:#020617}.video details{margin-top:1rem;color:var(--muted);font-size:.8rem}.video article{padding:.5rem 0}.video article h4{color:var(--accent);margin:0}.video article p{color:var(--secondary);line-height:1.6}</style>
