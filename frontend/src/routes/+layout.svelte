<script lang="ts">
  import '../app.css';
  let { children } = $props();
</script>

<div class="flex h-[100dvh] overflow-hidden">
  {@render children()}
</div>
