<script lang="ts">
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';
  import { buildVideoCaptions } from '$lib/video-captions';
  type Segment = { chapter: string; text: string; speaker: string; start_seconds?:number; end_seconds?:number; sources?:SourceReference[] };
  let { title, mediaUrl, content, limitations, sourceCommit, durationSeconds, initialTime, onTimeChange = () => {} }: { title:string; mediaUrl:string; content:{segments:Segment[]}; limitations:string[]; sourceCommit:string; durationSeconds?:number; initialTime?:number; onTimeChange?:(seconds:number)=>void }=$props();
  let captionsUrl = $state('data:text/vtt,WEBVTT%0A%0A');
  let video: HTMLVideoElement;
  let lastReportedSecond = -1;

  function ready() {
    if (initialTime !== undefined && Number.isFinite(initialTime)) video.currentTime = initialTime;
    lastReportedSecond = Math.floor(video.currentTime);
    onTimeChange(video.currentTime);
  }

  function reportTime() {
    const second = Math.floor(video.currentTime);
    if (second === lastReportedSecond) return;
    lastReportedSecond = second;
    onTimeChange(video.currentTime);
  }

  $effect(() => {
    const captions = buildVideoCaptions(content.segments, durationSeconds);
    const url = URL.createObjectURL(new Blob([captions], { type: 'text/vtt' }));
    captionsUrl = url;
    return () => URL.revokeObjectURL(url);
  });
</script>
<section class="video" aria-label="Video lesson player"><span class="eyebrow">English explainer video</span><h3>{title}</h3><video bind:this={video} controls preload="metadata" src={mediaUrl} aria-describedby="video-transcript" onloadedmetadata={ready} ontimeupdate={reportTime}><track kind="captions" src={captionsUrl} srclang="en" label="English" default/>Your browser does not support HTML video.</video><details id="video-transcript"><summary>Accessible transcript</summary>{#each content.segments as segment}<article><h4>{segment.chapter}</h4><p>{segment.text}</p>{#if segment.sources}<SourceLinks sources={segment.sources} {sourceCommit} compact />{/if}</article>{/each}</details><details><summary>What this does not prove</summary><ul>{#each limitations as item}<li>{item}</li>{/each}</ul></details></section>
<style>.video{border:1px solid var(--border);border-radius:1rem;background:var(--panel);padding:1rem}.video h3{font-size:1.5rem;margin:.5rem 0 1rem}.video video{display:block;width:100%;border-radius:.75rem;background:#020617}.video details{margin-top:1rem;color:var(--muted);font-size:.8rem}.video article{padding:.5rem 0}.video article h4{color:var(--accent);margin:0}.video article p{color:var(--secondary);line-height:1.6}</style>
