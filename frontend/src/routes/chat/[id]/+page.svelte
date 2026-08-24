<script lang="ts">import Workbench from '$lib/components/Workbench.svelte'; let { data }: { data: { id: string } } = $props();</script>
<Workbench initialId={data.id} />
