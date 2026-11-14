<script lang="ts">
	import { Avatar, Badge, Button, EmbeddingWord, Icon, StateMessage, Typography } from '#lib';

	let {
		activeWord,
		onword
	}: {
		activeWord: string | null;
		onword: (word: string) => void;
	} = $props();

	const clinicalTokens = [
		{ text: '67-year-old' },
		{ text: 'woman' },
		{ text: 'with' },
		{ text: 'an' },
		{ text: 'enlarging', score: 0.74 },
		{ text: 'keratotic', score: 0.91 },
		{ text: 'lesion', score: 0.69 },
		{ text: 'of' },
		{ text: 'the' },
		{ text: 'left' },
		{ text: 'forearm.', score: 0.63 },
		{ text: 'Excision' },
		{ text: 'for' },
		{ text: 'histological', score: 0.71 },
		{ text: 'review.' },
		{ text: 'No' },
		{ text: 'prior' },
		{ text: 'cutaneous', score: 0.77 },
		{ text: 'malignancy', score: 0.82 },
		{ text: 'documented.' }
	];

	function clearActiveWord() {
		if (activeWord) onword(activeWord);
	}
</script>

<div class="panel-content report-panel">
	<div class="panel-heading">
		<div>
			<Typography style="eyebrow" tone="accent">S-03 · Report</Typography>
			<Typography as="h2" style="section">Pathology report</Typography>
		</div>
		<Button variant="ghost" icon="more" iconOnly ariaLabel="Report actions" />
	</div>

	<StateMessage
		tone="warning"
		title="This open case has not been reported"
		description="Only submitted context is available. Hover highlighted terms to inspect image-embedding similarity."
	/>

	<div class="author-card">
		<Avatar name="Dr A. Okafor" />
		<div>
			<Typography style="label">Assigned to Dr A. Okafor</Typography>
			<Typography style="small" tone="muted">Consultant Histopathologist</Typography>
		</div>
		<Badge tone="synthetic">Synthetic identity</Badge>
	</div>

	<div class="context-guide">
		<Icon name="heatmap" size="sm" />
		<div>
			<Typography style="label">Explore report context on the slide</Typography>
			<Typography style="small" tone="secondary">
				Informative, non-stop words reveal themselves on hover. Select one to map its embedding
				similarity.
			</Typography>
		</div>
	</div>

	<section class="report-section">
		<Typography style="eyebrow" tone="muted">Clinical history</Typography>
		<div class="context-copy">
			{#each clinicalTokens as token, index (index)}
				{#if token.score}
					<EmbeddingWord
						word={token.text}
						score={token.score}
						active={activeWord === token.text}
						onselect={onword}
					/>
				{:else}
					<span>{token.text}</span>
				{/if}&nbsp;
			{/each}
		</div>
	</section>

	<section class="report-section muted-section">
		<Typography style="eyebrow" tone="muted">Gross description</Typography>
		<Typography tone="muted">Available after sign-out.</Typography>
	</section>

	<section class="report-section muted-section">
		<Typography style="eyebrow" tone="muted">Microscopic description</Typography>
		<Typography tone="muted">Available after sign-out.</Typography>
	</section>

	{#if activeWord}
		<div class="active-term">
			<div>
				<Typography style="eyebrow" tone="accent">Mapped from report context</Typography>
				<Typography style="section">“{activeWord}”</Typography>
			</div>
			<button class="clear-term" type="button" onclick={clearActiveWord}>
				<Icon name="close" size="sm" />
				Clear
			</button>
		</div>
	{/if}

	<div class="panel-footnote">
		<Icon name="warning" size="sm" />
		<Typography style="small" tone="muted">
			The overlay is word-to-patch embedding similarity, not a finding or diagnosis.
		</Typography>
	</div>
</div>

<style>
	.panel-content {
		display: grid;
		align-content: start;
		gap: var(--space-5);
		padding: var(--space-5);
	}
	.panel-heading,
	.author-card,
	.context-guide,
	.active-term {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.panel-heading > div,
	.author-card > div,
	.context-guide > div,
	.active-term > div {
		display: grid;
		gap: var(--space-1);
	}
	.author-card {
		justify-content: flex-start;
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-surface-subtle);
	}
	.author-card > :global(.badge) {
		margin-left: auto;
	}
	.context-guide {
		align-items: flex-start;
		justify-content: flex-start;
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-info-border);
		border-radius: var(--radius-md);
		background: var(--color-info-soft);
		color: var(--color-info);
	}
	.report-section {
		display: grid;
		gap: var(--space-3);
		padding-bottom: var(--space-5);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.context-copy {
		color: var(--color-text);
		font: var(--font-body);
		line-height: 2;
	}
	.muted-section {
		opacity: 0.72;
	}
	.active-term {
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-action);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
	}
	.clear-term {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-2);
		border: 0;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
		cursor: pointer;
	}
	.clear-term:hover,
	.clear-term:focus-visible {
		background: var(--color-surface-raised);
		color: var(--color-text);
		outline: none;
	}
	.panel-footnote {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		padding-top: var(--space-2);
	}
</style>
