<script lang="ts">
	import { Typography } from '#lib';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	const pending = $derived(caseState.pendingAnnotationRegion);
</script>

<div class="panel-placeholder">
	<Typography style="eyebrow" tone="muted">Annotations</Typography>
	<Typography as="h2" style="section">Mark a region</Typography>
	{#if pending}
		<Typography tone="secondary">
			A region is ready to label on {pending.slideId}: {Math.round(pending.width)} × {Math.round(
				pending.height
			)} px at ({Math.round(pending.x)}, {Math.round(pending.y)}).
		</Typography>
	{:else}
		<Typography tone="secondary">
			Select tissue and choose Annotate. Marks stay on the slide and can be hidden from the layer
			control.
		</Typography>
	{/if}
</div>

<style>
	.panel-placeholder {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-5);
	}
</style>
