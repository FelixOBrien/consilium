<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		Avatar,
		Badge,
		Button,
		EmptyState,
		Icon,
		Pressable,
		Skeleton,
		TissueImage,
		Typography
	} from '#lib';
	import { cases, tissueImages } from '#lib/data.js';
	import AnnotationsPanel from '#lib/workspace/AnnotationsPanel.svelte';
	import ConsultPanel from '#lib/workspace/ConsultPanel.svelte';
	import EvidencePanel from '#lib/workspace/EvidencePanel.svelte';
	import ReportPanel from '#lib/workspace/ReportPanel.svelte';
	import SlideViewer from '#lib/workspace/SlideViewer.svelte';

	let panel = $state('report');
	let panelVisible = $state(true);
	let activeWord = $state<string | null>(null);
	let currentSlide = $state(0);
	let screenState = $state('ready');
	const caseId = $derived(page.params.caseId);
	const caseRecord = $derived(cases.find((item) => item.id === caseId) ?? cases[0]);
	const panels = [
		{ value: 'report', label: 'Report', icon: 'report' as const },
		{ value: 'evidence', label: 'Evidence', icon: 'evidence' as const },
		{ value: 'consult', label: 'Consult', icon: 'spark' as const },
		{ value: 'annotations', label: 'Annotations', icon: 'annotation' as const }
	];

	function setPanel(next: string) {
		panel = next;
		panelVisible = true;
		const url = new URL(window.location.href);
		url.searchParams.set('panel', next);
		window.history.replaceState({}, '', url);
	}

	function toggleWord(word: string) {
		activeWord = activeWord === word ? null : word;
	}

	onMount(() => {
		panel = page.url.searchParams.get('panel') ?? 'report';
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
</script>

<svelte:head>
	<title>{caseId} · Consilium</title>
</svelte:head>

{#if screenState === 'not-found'}
	<div class="page">
		<section class="surface">
			<EmptyState
				icon="warning"
				title="Case not found"
				description="This case may not have been ingested or the link is no longer valid."
				action="Return to worklist"
				onaction={() => (window.location.href = '/')}
			/>
		</section>
	</div>
{:else if screenState === 'loading'}
	<div class="workspace-loading">
		<div class="case-header loading-header">
			<Skeleton height="lg" width="short" />
			<Skeleton width="medium" />
		</div>
		<div class="loading-workspace">
			<Skeleton height="xl" />
			<div><Skeleton height="lg" /><Skeleton /><Skeleton /><Skeleton /></div>
		</div>
	</div>
{:else}
	<div class="workspace">
		<header class="case-header">
			<div class="case-identity">
				<Button href="/" variant="ghost" icon="arrow-left" iconOnly ariaLabel="Back to worklist" />
				<div>
					<div class="case-title-row">
						<Typography as="h1" style="section">{caseRecord.id}</Typography>
						<Badge tone={caseRecord.status === 'Open' ? 'warning' : 'success'}>
							{caseRecord.status}
						</Badge>
					</div>
					<div class="case-meta">
						<Typography style="small" tone="secondary">{caseRecord.specialty}</Typography>
						<span></span>
						<Typography style="small" tone="secondary">{caseRecord.ageSex}</Typography>
						<span></span>
						<Typography style="small" tone="secondary">{caseRecord.slides} slides</Typography>
						{#if caseRecord.status === 'Signed out'}
							<span></span>
							<Typography style="mono" tone="secondary">{caseRecord.icd10}</Typography>
						{/if}
					</div>
				</div>
			</div>

			<div class="case-actions">
				<div class="assigned">
					<Avatar name={caseRecord.pathologist} size="sm" />
					<div>
						<Typography style="small" tone="muted">Assigned pathologist</Typography>
						<Typography style="label">{caseRecord.pathologist}</Typography>
					</div>
					<Badge tone="synthetic">Synthetic</Badge>
				</div>
				<Button variant="secondary" size="sm" icon="copy">Copy view link</Button>
				<Button variant="ghost" icon="more" iconOnly ariaLabel="More case actions" />
			</div>
		</header>

		<div class="workspace-body" class:panel-hidden={!panelVisible}>
			<aside class="slide-rail" aria-label="Case slides">
				<div class="rail-heading">
					<Icon name="grid" size="sm" />
					<Typography style="eyebrow" tone="muted">Slides</Typography>
				</div>
				{#each [tissueImages.wholeSlide, tissueImages.epithelium] as slide, index (slide)}
					<Pressable
						className="slide-button"
						selected={currentSlide === index}
						onclick={() => (currentSlide = index)}
					>
						<TissueImage src={slide} alt={`Slide ${index + 1}`} size="md" />
						<span>
							<Typography style="label">S{index + 1}</Typography>
							<Typography style="small" tone="muted">H&E · 20×</Typography>
						</span>
						<Badge tone="success">Ready</Badge>
					</Pressable>
				{/each}
				<div class="rail-foot">
					<Typography style="small" tone="muted">38,412 × 26,904 px</Typography>
					<Typography style="small" tone="muted">0.5 μm/px</Typography>
				</div>
			</aside>

			<div class="viewer-region">
				<SlideViewer onpanel={setPanel} {activeWord} onclearword={() => (activeWord = null)} />
				{#if !panelVisible}
					<div class="panel-reopen">
						<Button variant="secondary" icon="panel" onclick={() => (panelVisible = true)}>
							Show panel
						</Button>
					</div>
				{/if}
			</div>

			{#if panelVisible}
				<aside class="side-panel">
					<div class="panel-tabs" role="tablist">
						{#each panels as item (item.value)}
							<Pressable
								className="panel-tab"
								selected={panel === item.value}
								role="tab"
								ariaSelected={panel === item.value}
								onclick={() => setPanel(item.value)}
							>
								<Icon name={item.icon} size="sm" />
								<span>{item.label}</span>
							</Pressable>
						{/each}
						<Button
							variant="ghost"
							size="sm"
							icon="panel"
							iconOnly
							ariaLabel="Hide side panel"
							onclick={() => (panelVisible = false)}
						/>
					</div>
					<div class="panel-scroll">
						{#if panel === 'report'}
							<ReportPanel {activeWord} onword={toggleWord} />
						{:else if panel === 'evidence'}
							<EvidencePanel />
						{:else if panel === 'consult'}
							<ConsultPanel />
						{:else}
							<AnnotationsPanel />
						{/if}
					</div>
				</aside>
			{/if}
		</div>
	</div>
{/if}

<style>
	.workspace {
		height: calc(100dvh - var(--header-height) - var(--notice-height));
		overflow: hidden;
		background: var(--color-surface);
	}
	.case-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		min-height: 4.5rem;
		padding: var(--space-3) var(--space-5);
		border-bottom: var(--border-width) solid var(--color-border);
		background: var(--color-surface);
	}
	.case-identity,
	.case-title-row,
	.case-meta,
	.case-actions,
	.assigned {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.case-identity > div:last-child,
	.assigned > div {
		display: grid;
		gap: var(--space-1);
	}
	.case-title-row {
		gap: var(--space-2);
	}
	.case-meta {
		gap: var(--space-2);
	}
	.case-meta > span {
		width: var(--space-1);
		height: var(--space-1);
		border-radius: var(--radius-pill);
		background: var(--color-border-strong);
	}
	.assigned {
		padding-right: var(--space-4);
		border-right: var(--border-width) solid var(--color-border);
	}
	.workspace-body {
		display: grid;
		grid-template-columns: 10rem minmax(0, 1fr) var(--panel-width);
		height: calc(100% - 4.5rem);
	}
	.workspace-body.panel-hidden {
		grid-template-columns: 10rem minmax(0, 1fr);
	}
	.slide-rail {
		display: grid;
		align-content: start;
		gap: var(--space-2);
		padding: var(--space-3);
		overflow-y: auto;
		border-right: var(--border-width) solid var(--color-border);
		background: var(--color-surface-raised);
	}
	.rail-heading {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2);
	}
	.slide-rail :global(button.slide-button) {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-2);
		border: var(--border-width) solid transparent;
		border-radius: var(--radius-md);
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.slide-rail :global(button.slide-button:hover),
	.slide-rail :global(button.slide-button.selected) {
		background: var(--color-surface);
		border-color: var(--color-border);
		box-shadow: var(--shadow-sm);
	}
	.slide-rail :global(button.slide-button .tissue) {
		width: 100%;
		height: 4.5rem;
	}
	.slide-rail :global(button.slide-button > span) {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.rail-foot {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-3) var(--space-2);
		border-top: var(--border-width) solid var(--color-border);
	}
	.viewer-region {
		position: relative;
		min-width: 0;
		overflow: hidden;
	}
	.panel-reopen {
		position: absolute;
		z-index: 2;
		top: var(--space-4);
		right: var(--space-4);
	}
	.side-panel {
		display: grid;
		grid-template-rows: var(--panel-tabs-height) minmax(0, 1fr);
		min-width: 0;
		border-left: var(--border-width) solid var(--color-border);
		background: var(--color-surface);
	}
	.panel-tabs {
		display: grid;
		grid-template-columns: repeat(4, 1fr) auto;
		border-bottom: var(--border-width) solid var(--color-border);
		background: var(--color-surface-raised);
	}
	.panel-tabs :global(button.panel-tab) {
		position: relative;
		display: grid;
		place-items: center;
		align-content: center;
		gap: var(--space-1);
		border: 0;
		background: transparent;
		color: var(--color-text-muted);
		font: var(--font-label-xs);
		cursor: pointer;
	}
	.panel-tabs :global(button.panel-tab::after) {
		content: '';
		position: absolute;
		right: var(--space-3);
		bottom: 0;
		left: var(--space-3);
		height: 0.125rem;
		border-radius: var(--radius-pill);
		background: transparent;
	}
	.panel-tabs :global(button.panel-tab:hover),
	.panel-tabs :global(button.panel-tab.selected) {
		color: var(--color-action);
	}
	.panel-tabs :global(button.panel-tab.selected::after) {
		background: var(--color-action);
	}
	.panel-scroll {
		min-height: 0;
		overflow-y: auto;
	}
	.workspace-loading {
		padding: 0;
	}
	.loading-header {
		max-width: none;
	}
	.loading-workspace {
		display: grid;
		grid-template-columns: 1fr var(--panel-width);
		gap: var(--space-5);
		height: calc(100dvh - var(--header-height) - var(--notice-height) - 4.5rem);
		padding: var(--space-5);
		background: var(--color-viewer);
	}
	.loading-workspace > div {
		display: grid;
		align-content: start;
		gap: var(--space-4);
		padding: var(--space-4);
		background: var(--color-surface);
	}
	@media (max-width: 1260px) {
		.workspace-body {
			grid-template-columns: 6rem minmax(0, 1fr) var(--panel-width);
		}
		.workspace-body.panel-hidden {
			grid-template-columns: 6rem minmax(0, 1fr);
		}
		.slide-rail :global(button.slide-button > span),
		.slide-rail :global(button.slide-button .badge),
		.rail-foot {
			display: none;
		}
	}
	@media (max-width: 980px) {
		.workspace {
			height: auto;
			overflow: visible;
		}
		.workspace-body {
			grid-template-columns: var(--rail-width) minmax(0, 1fr);
			height: auto;
		}
		.side-panel {
			grid-column: 1 / -1;
			min-height: 42rem;
		}
		.case-header {
			align-items: flex-start;
			flex-direction: column;
		}
		.case-actions {
			width: 100%;
			justify-content: space-between;
		}
		.slide-rail {
			padding: var(--space-1);
		}
		.slide-rail :global(button.slide-button) {
			padding: var(--space-1);
		}
		.slide-rail :global(button.slide-button .tissue) {
			height: 2.75rem;
		}
	}
	@media (max-width: 620px) {
		.assigned {
			display: none;
		}
		.case-meta {
			flex-wrap: wrap;
		}
	}
</style>
