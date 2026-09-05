<script lang="ts">
  import SourceLinks from './SourceLinks.svelte';
  import type { SourceReference } from '$lib/source-links';
  type Segment = { chapter: string; text: string; speaker: string; sources?: SourceReference[] };
  let { title, mediaUrl, content, limitations, sourceCommit }: { title: string; mediaUrl: string; content: { segments: Segment[] }; limitations: string[]; sourceCommit:string } = $props();
  let audio: HTMLAudioElement;
  let speed = $state('1');
  function setSpeed() { if (audio) audio.playbackRate = Number(speed); }
  function seek(delta: number) { if (audio) audio.currentTime = Math.max(0, Math.min(audio.duration || Infinity, audio.currentTime + delta)); }
</script>
<section class="audio-card" aria-label="Audio lesson player">
  <span class="eyebrow">English audio lesson</span><h3>{title}</h3>
  <audio bind:this={audio} controls preload="metadata" src={mediaUrl}></audio>
  <div class="controls"><button onclick={() => seek(-15)} aria-label="Seek back 15 seconds">−15s</button><label>Speed <select bind:value={speed} onchange={setSpeed} aria-label="Playback speed"><option value="0.75">0.75×</option><option value="1">1×</option><option value="1.25">1.25×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></label><button onclick={() => seek(15)} aria-label="Seek forward 15 seconds">+15s</button></div>
  <div class="transcript"><h4>Transcript and chapters</h4>{#each content.segments as segment}<article><h5>{segment.chapter}</h5><p>{segment.text}</p>{#if segment.sources}<SourceLinks sources={segment.sources} {sourceCommit} compact />{/if}</article>{/each}</div>
  <details><summary>What this does not prove</summary><ul>{#each limitations as item}<li>{item}</li>{/each}</ul></details>
</section>
<style>.audio-card{border:1px solid var(--border);border-radius:1rem;background:var(--panel);padding:1rem}.audio-card h3{font-size:1.5rem;margin:.5rem 0 1rem}.audio-card audio{width:100%}.controls{display:flex;gap:.75rem;align-items:center;justify-content:center;margin:1rem 0}.controls button,.controls select{min-height:40px;border:1px solid var(--border);border-radius:.55rem;background:var(--bg);color:var(--text);padding:.45rem}.controls label{font-size:.75rem;color:var(--muted)}.transcript{max-height:420px;overflow:auto;border-top:1px solid var(--border);padding-top:1rem}.transcript article{padding:.5rem 0}.transcript h5{color:var(--accent);font-size:.8rem;margin:0}.transcript p{color:var(--secondary);line-height:1.65;font-size:.85rem}details{color:var(--muted);font-size:.8rem}</style>
