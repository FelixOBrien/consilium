<script lang="ts">
	import { Badge, Typography } from '#lib';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	const region = $derived(caseState.consultRegionAttachment);
	const cases = $derived(caseState.consultCasesAttachment);
</script>

<div class="panel-placeholder">
	<Typography style="eyebrow" tone="muted">Consult</Typography>
	<Typography as="h2" style="section">Ask about precedent</Typography>
	<Typography tone="secondary">
		Questions are answered from retrieved cases, with citations. This does not state a diagnosis for
		the open case.
	</Typography>
	{#if region}
		<div class="attachment">
			<Badge tone="info">Region attached</Badge>
			<Typography style="small" tone="secondary">
				Slide {region.slideId}, {Math.round(region.width)} × {Math.round(region.height)} px at ({Math.round(
					region.x
				)}, {Math.round(region.y)}).
			</Typography>
		</div>
	{/if}
	{#if cases}
		<div class="attachment">
			<Badge tone="info">{cases.caseIds.length} cases attached</Badge>
		</div>
	{/if}
</div>

<style>
	.panel-placeholder {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-5);
	}
	.attachment {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
</style>
