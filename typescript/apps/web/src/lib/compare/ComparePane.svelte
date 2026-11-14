<script lang="ts">
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { Badge, Button, Skeleton, StateMessage, Typography } from '#lib';
	import { OPEN_CASE_LABEL, PRECEDENT_LABEL, RELATIVE_SCALE_NOTE } from './copy.js';
	import { loadSlide, type SlideDetail, type SlideLoad } from './load.js';
	import type { PaneController } from './link.js';
	import { createViewer, destroyViewer, markerPixel, readView, writeView } from './osd.js';
	import { hasMpp, micronsPerScreenPixel, type PaneView } from './scale.js';
	import { caseViewSearch } from './url.js';

	let {
		slideId,
		side,
		restore,
		mark,
		relativeScale,
		onregister,
		ongesture,
		onmove,
		onsettle
	}: {
		slideId: string;
		side: 'left' | 'right';
		restore: { x: number | null; y: number | null; zoom: number | null };
		mark: { x: number; y: number } | null;
		relativeScale: boolean;
		onregister: (controller: PaneController, mpp: number | null) => void;
		ongesture: () => void;
		onmove: () => void;
		onsettle: () => void;
	} = $props();

	const role = $derived(side === 'left' ? OPEN_CASE_LABEL : PRECEDENT_LABEL);

	let load = $state<SlideLoad | null>(null);
	let tileError = $state(false);
	let opened = $state(false);
	let live = $state<PaneView | null>(null);
	let osdEl = $state<HTMLDivElement | null>(null);
	let markerEl = $state<HTMLDivElement | null>(null);
	let attempt = $state(0);

	let viewer: OpenSeadragon.Viewer | null = null;
	let suppress = false;
	let tileFailures = 0;
	// Assigned in an effect so the viewer is not recreated when the parent re-renders.
	const callbacks: {
		onregister: (controller: PaneController, mpp: number | null) => void;
		ongesture: () => void;
		onmove: () => void;
		onsettle: () => void;
	} = {
		onregister: () => undefined,
		ongesture: () => undefined,
		onmove: () => undefined,
		onsettle: () => undefined
	};

	$effect(() => {
		callbacks.onregister = onregister;
		callbacks.ongesture = ongesture;
		callbacks.onmove = onmove;
		callbacks.onsettle = onsettle;
	});

	const slide = $derived(load?.status === 'ready' ? load.slide : null);
	const paneState = $derived.by(() => {
		if (!load) return 'loading';
		if (load.status === 'not-found') return 'not-found';
		if (load.status === 'not-ready') return 'not-ready';
		if (load.status === 'error') return 'error';
		if (tileError) return 'tile-error';
		if (!opened) return 'loading';
		return 'ready';
	});
	const microns = $derived.by(() => {
		if (!slide || !hasMpp(slide.mpp) || !live || !(live.zoom > 0)) return null;
		return micronsPerScreenPixel(slide.mpp, live.zoom);
	});
	function read(): PaneView | null {
		return viewer ? readView(viewer) : live;
	}

	function apply(view: PaneView) {
		if (!viewer) return;
		suppress = true;
		try {
			writeView(viewer, view);
			live = readView(viewer) ?? view;
			placeMarker();
		} finally {
			suppress = false;
		}
	}

	function zoomBy(factor: number) {
		if (!viewer) return;
		callbacks.ongesture();
		viewer.viewport.zoomBy(factor);
		viewer.viewport.applyConstraints();
	}

	const controller: PaneController = { read, apply, zoomBy };

	function placeMarker() {
		if (!viewer || !markerEl || !mark) return;
		const pixel = markerPixel(viewer, mark.x, mark.y);
		if (!pixel) return;
		markerEl.style.left = `${pixel.x}px`;
		markerEl.style.top = `${pixel.y}px`;
	}

	function publishMove() {
		if (suppress || !viewer) return;
		live = readView(viewer);
		placeMarker();
		callbacks.onmove();
	}

	function restoreView(created: OpenSeadragon.Viewer) {
		const current = readView(created);
		if (!current) return;
		if (restore.x == null && restore.y == null && restore.zoom == null) return;
		writeView(created, {
			x: restore.x ?? current.x,
			y: restore.y ?? current.y,
			zoom: restore.zoom ?? current.zoom
		});
	}

	function wire(created: OpenSeadragon.Viewer) {
		created.addHandler('open', () => {
			restoreView(created);
			opened = true;
			tileError = false;
			live = readView(created);
			placeMarker();
			if (load?.status === 'ready') callbacks.onregister(controller, load.slide.mpp);
		});
		created.addHandler('open-failed', () => {
			tileError = true;
		});
		created.addHandler('tile-load-failed', () => {
			if (viewer !== created) return;
			tileFailures += 1;
			if (tileFailures >= 3) tileError = true;
		});
		created.addHandler('canvas-drag', () => callbacks.ongesture());
		created.addHandler('canvas-scroll', () => callbacks.ongesture());
		created.addHandler('canvas-pinch', () => callbacks.ongesture());
		created.addHandler('canvas-key', () => callbacks.ongesture());
		created.addHandler('pan', () => publishMove());
		created.addHandler('zoom', () => publishMove());
		created.addHandler('animation', () => publishMove());
		created.addHandler('animation-finish', () => {
			live = readView(created);
			placeMarker();
			callbacks.onsettle();
		});
		created.addHandler('update-viewport', () => placeMarker());
	}

	function mountViewer(element: HTMLDivElement, source: SlideDetail) {
		const created = createViewer(element, source.dzi_url);
		viewer = created;
		wire(created);
		return () => {
			destroyViewer(created);
			if (viewer === created) viewer = null;
		};
	}

	function retryMetadata() {
		opened = false;
		tileError = false;
		tileFailures = 0;
		load = null;
		void loadSlide(slideId).then((result) => {
			load = result;
		});
	}

	function retryTiles() {
		tileError = false;
		tileFailures = 0;
		opened = false;
		attempt += 1;
	}

	onMount(() => {
		let active = true;
		void loadSlide(slideId).then((result) => {
			if (active) load = result;
		});
		return () => {
			active = false;
			destroyViewer(viewer);
			viewer = null;
		};
	});

	$effect(() => {
		const element = osdEl;
		const source = slide;
		void attempt;
		if (!element || !source) return;
		return mountViewer(element, source);
	});

	function magnification(value: number): string {
		const rounded = Number(value.toFixed(1));
		return Number.isInteger(rounded) ? `${rounded.toFixed(0)}×` : `${rounded}×`;
	}

	function stainLabel(stain: string): string {
		return stain === 'HE' ? 'H&E' : stain;
	}
</script>

<section class="pane" data-pane={side} data-state={paneState} aria-label="{role} slide">
	<header class="pane-header">
		<div class="heading">
			<div class="title-row">
				<Badge tone={side === 'left' ? 'accent' : 'info'}>{role}</Badge>
				{#if slide}
					<Typography as="span" style="label">{slide.case_id}</Typography>
				{:else}
					<Typography as="span" style="label" tone="muted">{slideId}</Typography>
				{/if}
			</div>
			{#if load?.status === 'ready'}
				<Typography as="p" style="small" tone="secondary">
					{#if load.specimenLabel}{load.specimenLabel} ·
					{/if}
					Slide {load.slide.ordinal} · {stainLabel(load.slide.stain)} · {magnification(
						load.slide.magnification
					)} · {load.slide.mpp.toFixed(2)} µm/px
				</Typography>
				<p class="scale" data-testid="microns" data-microns={microns ?? ''}>
					{#if microns != null}
						{microns.toFixed(3)} µm/screen px
					{:else}
						Scale follows relative zoom
					{/if}
				</p>
			{/if}
			{#if relativeScale && load?.status === 'ready'}
				<Typography as="p" style="small" tone="secondary">{RELATIVE_SCALE_NOTE}</Typography>
			{/if}
		</div>
		<div class="header-actions">
			{#if paneState === 'ready'}
				<Button
					variant="secondary"
					size="sm"
					icon="zoom-out"
					iconOnly
					ariaLabel="Zoom out"
					onclick={() => zoomBy(1 / 1.4)}
				/>
				<Button
					variant="secondary"
					size="sm"
					icon="zoom-in"
					iconOnly
					ariaLabel="Zoom in"
					onclick={() => zoomBy(1.4)}
				/>
			{/if}
			{#if slide}
				<!-- eslint-disable svelte/no-navigation-without-resolve -- viewport query is not a route id -->
				<a
					class="open-case"
					href={`${resolve('/cases/[caseId]', { caseId: slide.case_id })}?${caseViewSearch(slide.id, live)}`}
				>
					Open case
				</a>
				<!-- eslint-enable svelte/no-navigation-without-resolve -->
			{/if}
		</div>
	</header>

	<div class="stage">
		{#if slide}
			<div class="osd" bind:this={osdEl}></div>
			{#if mark}
				<div class="locus" bind:this={markerEl}>
					<span>Compared locus</span>
				</div>
			{/if}
		{/if}

		{#if paneState === 'loading'}
			<div class="overlay">
				<Skeleton height="lg" />
				<Typography style="small" tone="secondary">Loading slide…</Typography>
			</div>
		{:else if paneState === 'not-found'}
			<div class="overlay">
				<StateMessage
					tone="warning"
					title="Slide not found"
					description={load?.status === 'not-found' ? load.message : 'Slide not found.'}
				/>
			</div>
		{:else if paneState === 'not-ready'}
			<div class="overlay">
				<StateMessage
					tone="warning"
					title="Slide not ready"
					description={load?.status === 'not-ready' ? load.message : 'Slide is not ready.'}
				/>
			</div>
		{:else if paneState === 'error'}
			<div class="overlay">
				<StateMessage
					tone="danger"
					title="Slide could not be loaded"
					description={load?.status === 'error' ? load.message : 'The slide could not be loaded.'}
					action="Retry"
					onaction={retryMetadata}
				/>
			</div>
		{:else if paneState === 'tile-error'}
			<div class="overlay overlay-banner">
				<StateMessage
					tone="danger"
					title="Tiles failed to load"
					description="The slide image could not be read. The other pane is unchanged."
					action="Retry"
					onaction={retryTiles}
				/>
			</div>
		{/if}
	</div>
</section>

<style>
	.pane {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		min-width: 0;
		min-height: 0;
		background: var(--color-viewer);
		color: var(--color-viewer-text);
	}
	.pane-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		background: var(--color-surface);
		color: var(--color-text);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.heading {
		display: grid;
		gap: var(--space-1);
		min-width: 0;
	}
	.title-row,
	.header-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.header-actions {
		flex-shrink: 0;
	}
	.scale {
		margin: 0;
		font: var(--font-mono);
		color: var(--color-text-secondary);
	}
	.open-case {
		font: var(--font-label-sm);
		color: var(--color-action);
		text-decoration: none;
		white-space: nowrap;
	}
	.open-case:hover {
		text-decoration: underline;
	}
	.stage {
		position: relative;
		min-height: 0;
		background: var(--color-viewer);
	}
	.osd {
		position: absolute;
		inset: 0;
		background: var(--color-viewer);
	}
	.osd :global(.openseadragon-container) {
		background: var(--color-viewer) !important;
	}
	.locus {
		position: absolute;
		z-index: 3;
		width: 1.75rem;
		height: 1.75rem;
		border: 2px solid #fff4dc;
		border-radius: 50%;
		box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.55);
		transform: translate(-50%, -50%);
		pointer-events: none;
	}
	.locus::after {
		content: '';
		position: absolute;
		top: 50%;
		left: 50%;
		width: 0.375rem;
		height: 0.375rem;
		border-radius: 50%;
		background: #fff4dc;
		transform: translate(-50%, -50%);
	}
	.locus span {
		position: absolute;
		top: calc(100% + 0.25rem);
		left: 50%;
		padding: 0.1rem 0.35rem;
		border-radius: var(--radius-sm);
		background: rgba(20, 25, 29, 0.86);
		color: #fff4dc;
		font: var(--font-label-xs);
		white-space: nowrap;
		transform: translateX(-50%);
	}
	.overlay {
		position: absolute;
		inset: 0;
		z-index: 4;
		display: grid;
		align-content: center;
		justify-items: center;
		gap: var(--space-3);
		padding: var(--space-6);
		background: color-mix(in srgb, var(--color-viewer) 88%, transparent);
	}
	.overlay-banner {
		inset: auto var(--space-4) var(--space-4) var(--space-4);
		align-content: stretch;
		background: transparent;
	}
	.overlay :global(.state-message) {
		width: min(100%, 28rem);
	}
</style>
