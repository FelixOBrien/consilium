<script lang="ts">
	import { Typography } from '#lib';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	const openCase = $derived(caseState.caseDetail?.status === 'open');
</script>

<div class="panel-placeholder">
	<Typography style="eyebrow" tone="muted">Report</Typography>
	<Typography as="h2" style="section">
		{openCase ? 'Not yet reported' : 'Report'}
	</Typography>
	<Typography tone="secondary">
		{#if openCase}
			This case is not yet reported. An open case shows clinical history only, and no conclusion or
			ICD-10.
		{:else}
			The signed-out report for this case will appear here, with citations back to the case.
		{/if}
	</Typography>
</div>

<style>
	.panel-placeholder {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-5);
	}
</style>
