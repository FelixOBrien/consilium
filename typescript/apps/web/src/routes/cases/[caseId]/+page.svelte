<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		Avatar,
		Badge,
		Button,
		EmptyState,
		Icon,
		Pressable,
		Skeleton,
		StateMessage,
		Typography
	} from '#lib';
	import { formatAgeSex } from '#lib/worklist/present.js';
	import { specialtyLabel } from '#lib/worklist/query.js';
	import AnnotationsPanel from '#lib/workspace/AnnotationsPanel.svelte'; // pragma: allowlist secret
	import ConsultPanel from '#lib/workspace/ConsultPanel.svelte'; // pragma: allowlist secret
	import EvidencePanel from '#lib/workspace/EvidencePanel.svelte'; // pragma: allowlist secret
	import HeatmapControls from '#lib/workspace/HeatmapControls.svelte'; // pragma: allowlist secret
	import ReportPanel from '#lib/workspace/ReportPanel.svelte'; // pragma: allowlist secret
	import SlideViewer from '#lib/workspace/SlideViewer.svelte'; // pragma: allowlist secret
	import { setWorkspaceContext, WorkspaceState } from '#lib/workspace/workspace-state.svelte.js'; // pragma: allowlist secret
	import type { PanelId } from '#lib/workspace/viewport-url.js'; // pragma: allowlist secret
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const caseState = new WorkspaceState(); // pragma: allowlist secret
	setWorkspaceContext(caseState); // pragma: allowlist secret

	let copied = $state(false);
	let copyTimer = 0;
	let hiddenThumbs = $state<Record<string, boolean>>({});
	const productName = 'Consilium'; // pragma: allowlist secret

	const panels: {
		id: PanelId;
		label: string;
		icon: 'report' | 'evidence' | 'spark' | 'annotation';
	}[] = [
		{ id: 'report', label: 'Report', icon: 'report' },
		{ id: 'evidence', label: 'Evidence', icon: 'evidence' },
		{ id: 'consult', label: 'Consult', icon: 'spark' },
		{ id: 'annotations', label: 'Annotations', icon: 'annotation' }
	];

	const detail = $derived(caseState.caseDetail);
	const slides = $derived([...(detail?.slides ?? [])].sort((a, b) => a.ordinal - b.ordinal));
	const multiSlide = $derived(slides.length > 1);
	const signedOut = $derived(detail?.status === 'signed_out');

	$effect(() => {
		const caseId = data.caseId;
		void caseState.openCase(caseId, page.url.searchParams);
	});

	function slideStatusLabel(status: string): string {
		if (status === 'ready') return 'Ready';
		if (status === 'processing') return 'Ingesting';
		if (status === 'failed') return 'Failed';
		return 'Pending';
	}

	function slideStatusTone(status: string): 'success' | 'info' | 'warning' | 'danger' {
		if (status === 'ready') return 'success';
		if (status === 'processing') return 'info';
		if (status === 'failed') return 'danger';
		return 'warning';
	}

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			copied = true;
			window.clearTimeout(copyTimer);
			copyTimer = window.setTimeout(() => {
				copied = false;
			}, 2000);
		} catch {
			copied = false;
		}
	}
</script>

<svelte:head>
	<title>{data.caseId} · {productName}</title>
</svelte:head>

{#if caseState.casePhase === 'not-found'}
	<div class="page">
		<section class="surface">
			<EmptyState
				icon="warning"
				title="Case not found"
				description="This case may not have been ingested, or the link is no longer valid."
				action="Return to worklist"
				onaction={() => goto(resolve('/'))}
			/>
		</section>
	</div>
{:else if caseState.casePhase === 'error'}
	<div class="page">
		<section class="surface">
			<StateMessage
				tone="danger"
				title="Case unavailable"
				description={caseState.caseError ?? 'The case could not be loaded.'}
				action="Retry"
				onaction={() => caseState.retryCase()}
			/>
		</section>
	</div>
{:else if caseState.casePhase === 'loading' || !detail}
	<div class="case-loading" aria-busy="true" aria-label="Loading case">
		<div class="case-header loading-header">
			<Skeleton height="lg" width="short" />
			<Skeleton width="medium" />
		</div>
		<div class="loading-body">
			<Skeleton height="xl" />
			<div>
				<Skeleton height="lg" />
				<Skeleton />
				<Skeleton />
				<Skeleton />
			</div>
		</div>
	</div>
{:else}
	<div class="case-shell">
		<header class="case-header">
			<div class="case-identity">
				<Button href="/" variant="ghost" icon="arrow-left" iconOnly ariaLabel="Back to worklist" />
				<div>
					<div class="case-title-row">
						<Typography as="h1" style="section">{detail.id}</Typography>
						<Badge tone={signedOut ? 'success' : 'warning'}>
							{signedOut ? 'Signed out' : 'Not yet reported'}
						</Badge>
					</div>
					<div class="case-meta">
						<a
							class="patient-link"
							href={resolve('/patients/[patientId]', { patientId: detail.patient.id })}
						>
							{detail.patient.display_label}
						</a>
						{#if detail.prior_case_count > 0}
							<a
								class="prior-badge"
								href={resolve('/patients/[patientId]', { patientId: detail.patient.id })}
							>
								{detail.prior_case_count} prior
							</a>
						{/if}
						<span></span>
						<Typography style="small" tone="secondary">
							{detail.specimen_label ?? 'Specimen not recorded'}
						</Typography>
						<span></span>
						<Typography style="small" tone="secondary"
							>{specialtyLabel(detail.specialty)}</Typography
						>
						<span></span>
						<Typography style="small" tone="secondary">
							{formatAgeSex(detail.patient_age, detail.patient_sex)}
						</Typography>
						{#if signedOut && detail.icd10}
							<span></span>
							<Typography style="mono" tone="secondary">{detail.icd10}</Typography>
						{/if}
					</div>
				</div>
			</div>

			<div class="case-actions">
				<div class="assigned">
					<Avatar name={detail.assigned_to.name} size="sm" />
					<div>
						<Typography style="small" tone="muted">Assigned pathologist</Typography>
						<Typography style="label">{detail.assigned_to.name}</Typography>
					</div>
					{#if detail.assigned_to.is_synthetic}
						<Badge tone="synthetic">Synthetic</Badge>
					{/if}
				</div>
				<Button variant="secondary" size="sm" icon="copy" onclick={copyLink}>
					{copied ? 'Link copied' : 'Copy link'}
				</Button>
			</div>
		</header>

		<div class="case-body" class:single={!multiSlide} class:panel-hidden={!caseState.panelVisible}>
			{#if multiSlide}
				<aside class="slide-rail" aria-label="Case slides">
					<div class="rail-heading">
						<Icon name="grid" size="sm" />
						<Typography style="eyebrow" tone="muted">Slides</Typography>
					</div>
					{#each slides as slide (slide.id)}
						<Pressable
							className="slide-button"
							selected={caseState.activeSlideId === slide.id}
							onclick={() => caseState.selectSlide(slide.id)}
						>
							{#if slide.thumbnail_url && !hiddenThumbs[slide.id]}
								<img
									src={slide.thumbnail_url}
									alt=""
									onerror={() => {
										hiddenThumbs[slide.id] = true;
									}}
								/>
							{:else}
								<span class="thumb-fallback"></span>
							{/if}
							<span>
								<Typography style="label">S{slide.ordinal}</Typography>
								<Typography style="small" tone="muted">{slide.stain}</Typography>
							</span>
							<Badge tone={slideStatusTone(slide.status)}>{slideStatusLabel(slide.status)}</Badge>
						</Pressable>
					{/each}
				</aside>
			{/if}

			<div class="viewer-region">
				{#if caseState.slidePhase === 'missing' && slides.length === 0}
					<div class="cover-note">
						<EmptyState
							icon="database"
							title="No slides"
							description="This case has no whole-slide images yet."
						/>
					</div>
				{:else}
					<SlideViewer />
				{/if}
				<HeatmapControls />
				{#if !caseState.panelVisible}
					<div class="panel-reopen">
						<Button variant="secondary" icon="panel" onclick={() => caseState.showPanel()}>
							Show panel
						</Button>
					</div>
				{/if}
			</div>

			{#if caseState.panelVisible}
				<aside class="side-panel">
					<div class="panel-tabs" role="tablist" aria-label="Case panels">
						{#each panels as item (item.id)}
							<Pressable
								className="panel-tab"
								selected={caseState.activePanel === item.id}
								role="tab"
								ariaSelected={caseState.activePanel === item.id}
								onclick={() => caseState.openPanel(item.id)}
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
							onclick={() => caseState.hidePanel()}
						/>
					</div>
					<div class="panel-scroll">
						{#if caseState.activePanel === 'report'}
							<ReportPanel />
						{:else if caseState.activePanel === 'evidence'}
							<EvidencePanel />
						{:else if caseState.activePanel === 'consult'}
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
	.case-shell {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
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
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.patient-link,
	.prior-badge {
		color: var(--color-action);
		font: var(--font-label-sm);
		text-decoration: none;
	}
	.prior-badge {
		padding: 0 var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--color-action-soft);
	}
	.patient-link:hover,
	.prior-badge:hover {
		text-decoration: underline;
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
	.case-body {
		display: grid;
		grid-template-columns: 10rem minmax(0, 1fr) var(--panel-width);
		min-height: 0;
	}
	.case-body.single {
		grid-template-columns: minmax(0, 1fr) var(--panel-width);
	}
	.case-body.panel-hidden {
		grid-template-columns: 10rem minmax(0, 1fr);
	}
	.case-body.single.panel-hidden {
		grid-template-columns: minmax(0, 1fr);
	}
	.slide-rail {
		display: grid;
		align-content: start;
		gap: var(--space-2);
		min-height: 0;
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
	.slide-rail :global(button.slide-button img),
	.thumb-fallback {
		width: 100%;
		height: 4.5rem;
		object-fit: cover;
		border-radius: var(--radius-sm);
		background: var(--color-image-placeholder);
	}
	.slide-rail :global(button.slide-button > span) {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.viewer-region {
		position: relative;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--color-viewer);
	}
	.cover-note {
		display: grid;
		place-items: center;
		height: 100%;
		background: var(--color-surface);
	}
	.panel-reopen {
		position: absolute;
		z-index: 8;
		top: var(--space-4);
		right: var(--space-4);
	}
	.side-panel {
		display: grid;
		grid-template-rows: var(--panel-tabs-height) minmax(0, 1fr);
		min-width: 0;
		min-height: 0;
		border-left: var(--border-width) solid var(--color-border);
		background: var(--color-surface);
	}
	.panel-tabs {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr)) auto;
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
	.page,
	.surface {
		min-height: calc(100dvh - var(--header-height) - var(--notice-height));
	}
	.surface {
		display: grid;
		place-items: center;
	}
	.case-loading {
		min-height: calc(100dvh - var(--header-height) - var(--notice-height));
	}
	.loading-header {
		max-width: none;
	}
	.loading-body {
		display: grid;
		grid-template-columns: minmax(0, 1fr) var(--panel-width);
		gap: var(--space-5);
		height: calc(100dvh - var(--header-height) - var(--notice-height) - 4.5rem);
		padding: var(--space-5);
		background: var(--color-viewer);
	}
	.loading-body > div {
		display: grid;
		align-content: start;
		gap: var(--space-4);
		padding: var(--space-4);
		background: var(--color-surface);
	}
	@media (max-width: 1260px) {
		.case-body {
			grid-template-columns: 6rem minmax(0, 1fr) var(--panel-width);
		}
		.case-body.panel-hidden {
			grid-template-columns: 6rem minmax(0, 1fr);
		}
		.slide-rail :global(button.slide-button > span),
		.slide-rail :global(button.slide-button .badge) {
			display: none;
		}
	}
	@media (max-width: 980px) {
		.case-shell {
			height: auto;
			overflow: visible;
		}
		.case-body,
		.case-body.single,
		.case-body.panel-hidden,
		.case-body.single.panel-hidden {
			grid-template-columns: minmax(0, 1fr);
			height: auto;
		}
		.slide-rail {
			grid-auto-flow: column;
			grid-auto-columns: 7rem;
			border-right: 0;
			border-bottom: var(--border-width) solid var(--color-border);
		}
		.viewer-region {
			min-height: var(--viewer-min-height);
		}
		.side-panel {
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
	}
	@media (max-width: 620px) {
		.assigned {
			display: none;
		}
	}
</style>
