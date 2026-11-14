<script lang="ts">
	import { resolve } from '$app/paths';
	import { Badge, Button, EmptyState, Skeleton, StateMessage, Typography } from '#lib';
	import type { ReportLoad } from './report-load.js';
	import {
		authorWorklistQuery,
		phraseAfterSelect,
		phrasesMatch,
		presentReport,
		readReportSelection,
		reportTextIntent,
		segmentReportText,
		type ReportDisplay
	} from './report-text.js';

	let {
		load,
		activePhrase = null,
		onPhrase,
		onFindSimilar,
		onretry,
		peek = null,
		idPrefix = 'report'
	}: {
		load: ReportLoad;
		activePhrase?: string | null;
		onPhrase?: (phrase: string | null) => void;
		onFindSimilar?: (text: string) => void;
		onretry?: () => void;
		peek?: { caseId: string; onopen: () => void } | null;
		idPrefix?: string;
	} = $props();

	let root = $state<HTMLElement | null>(null);
	let selectionText = $state<string | null>(null);

	const display = $derived<ReportDisplay | null>(
		load.phase === 'ready' ? presentReport(load.report) : null
	);
	const interactive = $derived(Boolean(onPhrase));

	$effect(() => {
		const node = root;
		if (!node || !onFindSimilar) return;
		const sync = () => {
			selectionText = readReportSelection(node);
		};
		document.addEventListener('selectionchange', sync);
		return () => document.removeEventListener('selectionchange', sync);
	});

	function chooseWord(word: string, event: MouseEvent) {
		if (!onPhrase) return;
		const button = event.currentTarget as HTMLButtonElement;
		const selected = window.getSelection();
		if (selected && !selected.isCollapsed && selected.rangeCount > 0) {
			const outside = [selected.anchorNode, selected.focusNode].some(
				(node) => node != null && !button.contains(node)
			);
			if (outside && selected.toString().trim().length > 1) return;
		}
		button.blur();
		onPhrase(phraseAfterSelect(activePhrase, word));
	}

	function findSimilar(text: string) {
		if (!onFindSimilar) return;
		const intent = reportTextIntent(text);
		if (!intent) return;
		onFindSimilar(intent.text);
	}
</script>

{#snippet prose(text: string)}
	<div class="prose" data-report-text>
		{#each segmentReportText(text) as span, index (index)}
			{#if span.kind === 'word' && interactive}
				<button
					type="button"
					class="target"
					class:active={phrasesMatch(activePhrase, span.text)}
					aria-pressed={phrasesMatch(activePhrase, span.text)}
					aria-label={phrasesMatch(activePhrase, span.text)
						? `Clear ${span.text}`
						: `Map ${span.text} on the slide`}
					data-target-word={span.text}
					data-hint="Embedding similarity, not a finding"
					onclick={(event) => chooseWord(span.text, event)}
				>
					{span.text}
				</button>
			{:else}
				{span.text}
			{/if}
		{/each}
	</div>
{/snippet}

{#snippet sectionBlock(id: string, label: string, text: string)}
	<section class="section" data-section={id} aria-labelledby={`${idPrefix}-${id}`}>
		<div class="section-head">
			<Typography as="h3" style="eyebrow" tone="muted">
				<span id={`${idPrefix}-${id}`}>{label}</span>
			</Typography>
			{#if onFindSimilar}
				<Button size="sm" variant="ghost" icon="search" onclick={() => findSimilar(text)}>
					Find cases like this
				</Button>
			{/if}
		</div>
		{@render prose(text)}
	</section>
{/snippet}

<article
	class="report"
	bind:this={root}
	data-report-phase={load.phase}
	data-active-phrase={activePhrase ?? ''}
	aria-label="Report"
>
	{#if load.phase === 'loading'}
		<div class="loading" aria-busy="true" aria-label="Loading report">
			<Skeleton width="medium" height="sm" />
			<Skeleton width="short" height="sm" />
			<Skeleton height="lg" />
			<Skeleton />
			<Skeleton />
			<Skeleton width="medium" />
		</div>
	{:else if load.phase === 'not-found'}
		<EmptyState
			icon="warning"
			title="Report not found"
			description="No report was found for this case."
		/>
	{:else if load.phase === 'error'}
		<StateMessage
			tone="danger"
			title="The report could not be loaded."
			description="The slide is unchanged."
			action="Retry"
			onaction={onretry}
		/>
	{:else if display}
		<header class="report-header">
			{#if peek}
				<div class="peek-case">
					<Typography style="eyebrow" tone="muted">Case</Typography>
					<Typography style="label">{peek.caseId}</Typography>
					<Button size="sm" variant="secondary" onclick={peek.onopen}>Open case</Button>
				</div>
			{/if}
			{#if display.kind === 'unreported'}
				<StateMessage
					tone="info"
					title="Not yet reported"
					description={display.blocks.length > 0
						? 'Only the clinical history is shown.'
						: undefined}
				/>
			{:else if display.author}
				<div class="author-row">
					<a class="author" href={resolve(`/?${authorWorklistQuery(display.author.id)}` as '/')}
						>{display.author.name}</a
					>
					<Typography style="small" tone="secondary">
						{display.signedAtLabel
							? `Sign-out ${display.signedAtLabel}`
							: 'Sign-out date not recorded'}
					</Typography>
					{#if display.synthetic}
						<span title="Author and sign-out date are synthetic.">
							<Badge tone="synthetic">Synthetic</Badge>
						</span>
					{/if}
					{#if interactive && activePhrase}
						<Button size="sm" variant="ghost" onclick={() => onPhrase?.(null)}>
							Clear {activePhrase}
						</Button>
					{/if}
				</div>
			{/if}
			{#if onFindSimilar && selectionText}
				<div class="selection-action">
					<Button
						size="sm"
						variant="secondary"
						icon="search"
						onclick={() => findSimilar(selectionText ?? '')}
					>
						Find cases like this
					</Button>
					<Typography style="small" tone="muted">Selected report text</Typography>
				</div>
			{/if}
		</header>

		{#if display.kind === 'unreported' && display.blocks.length === 0}
			<!-- Notice alone: no clinical history was recorded. -->
		{:else}
			{#each display.blocks as block (block.id)}
				{@render sectionBlock(block.id, block.label, block.text)}
			{/each}
			{#if display.body && display.bodyMode === 'inline'}
				{@render sectionBlock('body', 'Report text', display.body)}
			{:else if display.body && display.bodyMode === 'alongside'}
				<details class="full-report" open>
					<summary>Full report text</summary>
					{@render sectionBlock('body', 'Full report text', display.body)}
				</details>
			{:else if display.blocks.length === 0}
				<EmptyState
					icon="database"
					title="No report text"
					description="This report has no extracted text."
				/>
			{/if}
		{/if}
	{/if}
</article>

<style>
	.report {
		display: grid;
		gap: var(--space-5);
		min-width: 0;
		padding: var(--space-5);
	}
	.loading {
		display: grid;
		gap: var(--space-3);
	}
	.report-header,
	.author-row,
	.peek-case,
	.section-head,
	.selection-action {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.report-header,
	.section {
		display: grid;
		gap: var(--space-3);
	}
	.section-head {
		justify-content: space-between;
		user-select: none;
	}
	.author {
		color: var(--color-action);
		font: var(--font-label);
		text-decoration: none;
	}
	.author:hover {
		text-decoration: underline;
	}
	.prose {
		margin: 0;
		color: var(--color-text);
		font: var(--font-body);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.target {
		position: relative;
		display: inline;
		margin: 0;
		padding: 0 var(--space-1);
		border: 0;
		border-radius: var(--radius-xs);
		background: transparent;
		color: inherit;
		font: inherit;
		cursor: pointer;
		transition:
			background var(--motion-fast),
			box-shadow var(--motion-fast),
			color var(--motion-fast);
	}
	.target:hover,
	.target:focus-visible,
	.target.active {
		background: var(--color-action-soft);
		color: var(--color-action);
		box-shadow: inset 0 -0.125rem var(--color-action);
		outline: 0;
	}
	.target::after {
		content: attr(data-hint);
		position: absolute;
		z-index: var(--z-dialog);
		left: 50%;
		bottom: calc(100% + var(--space-2));
		width: max-content;
		max-width: 14rem;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-ink);
		color: var(--color-text-inverse);
		font: var(--font-label-xs);
		white-space: normal;
		opacity: 0;
		pointer-events: none;
		transform: translate(-50%, var(--space-1));
		transition:
			opacity var(--motion-fast),
			transform var(--motion-fast);
	}
	.target:hover::after,
	.target:focus-visible::after {
		opacity: 1;
		transform: translate(-50%, 0);
	}
	.full-report {
		display: grid;
		gap: var(--space-3);
	}
	.full-report summary {
		cursor: pointer;
		color: var(--color-text-secondary);
		font: var(--font-label);
	}
</style>
