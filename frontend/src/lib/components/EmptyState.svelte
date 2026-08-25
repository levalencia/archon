<script lang="ts">
  let { prompts, onSend }: { prompts: string[]; onSend: (text: string) => void } = $props();
</script>

<section class="empty-state">
  <div class="hero-mark">A</div>
  <p class="eyebrow">Agent operations</p>
  <h1>Make every answer<br><span>production-ready.</span></h1>
  <p>Run prompts, inspect evidence, and diagnose reliability signals in one focused workspace.</p>
  <div class="starter">
    <span>Start with a workflow</span>
    {#each prompts as prompt}
      <button onclick={() => onSend(prompt)}>{prompt}<b>→</b></button>
    {/each}
  </div>
</section>
