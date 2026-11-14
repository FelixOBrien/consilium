<script lang="ts">
	import { Typography } from '#lib';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	const intent = $derived(caseState.pendingEvidenceIntent);
</script>

<div class="panel-placeholder">
	<Typography style="eyebrow" tone="muted">Evidence</Typography>
	<Typography as="h2" style="section">Retrieve precedent</Typography>
	{#if intent?.kind === 'patch'}
		<Typography tone="secondary">
			Find similar tissue is ready for the selected patch. Matches are retrieved from other
			signed-out cases. This is not a finding.
		</Typography>
	{:else if intent?.kind === 'region'}
		<Typography tone="secondary">
			Find similar tissue is ready for the selected region. Matches are retrieved from other
			signed-out cases. This is not a finding.
		</Typography>
	{:else if intent?.kind === 'report_text'}
		<Typography tone="secondary">
			A report-text search is ready. Matches are retrieved precedent, not a finding.
		</Typography>
	{:else}
		<Typography tone="secondary">
			Select tissue, then choose Find similar tissue. Results are precedent from signed-out cases,
			not a finding.
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
