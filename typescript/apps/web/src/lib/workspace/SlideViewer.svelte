<script lang="ts">
	import { onMount } from 'svelte';
	import { ACTING_USER_HEADER, getActingUserId } from '#lib/identity/acting-user.js';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import { Badge, Button, CheckField, Icon, StateMessage, Typography } from '#lib';
	import {
		annotationAtPoint,
		drawAnnotationLayer,
		drawSearchHitLayer,
		drawSelectionLayer,
		LAYER_ORDER,
		prepareLayerCanvas,
		projectionFromVisibleBounds,
		scaleBarFor,
		searchHitAtPoint,
		type LayerId,
		type Level0Bounds
	} from './overlay-layers.js';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret

	function depend(...watched: unknown[]) {
		return watched.length;
	}

	let frame = $state<HTMLDivElement | null>(null);
	let host = $state<HTMLDivElement | null>(null);
	let heatmapCanvas = $state<HTMLCanvasElement | null>(null);
	let searchCanvas = $state<HTMLCanvasElement | null>(null);
	let annotationCanvas = $state<HTMLCanvasElement | null>(null);
	let selectionCanvas = $state<HTMLCanvasElement | null>(null);
	let viewerEpoch = $state(0);
	let fetching = $state(false);
	let showFetching = $state(false);
	let tileError = $state(false);
	let dragRect = $state<Level0Bounds | null>(null);
	let magnification = $state('—');
	let scaleLabel = $state('');
	let scalePx = $state(0);

	let viewer: import('openseadragon').Viewer | null = null;
	let osdPoint: (new (x?: number, y?: number) => import('openseadragon').Point) | null = null;
	let openedSlideId = '';
	let appliedCamera = 0;
	let holdUrl = true;
	let tileFailures = 0;
	let urlTimer = 0;
	let dragging = false;

	const canvasFor: Record<LayerId, () => HTMLCanvasElement | null> = {
		heatmap: () => heatmapCanvas,
		searchHits: () => searchCanvas,
		annotations: () => annotationCanvas,
		selection: () => selectionCanvas
	};

	function slideStatusCopy(status: string): { title: string; description: string } {
		if (status === 'failed') {
			return {
				title: 'Ingestion failed',
				description:
					'This slide has no image to view. Choose another slide, or check again after ingestion is retried.'
			};
		}
		if (status === 'processing') {
			return {
				title: 'Slide still ingesting',
				description:
					'The image appears here when ingestion finishes. The report and other panels stay available.'
			};
		}
		return {
			title: 'Slide not ready',
			description: 'This slide is waiting to be ingested, so there is no image yet.'
		};
	}

	function formatMagnification(value: number): string {
		if (!Number.isFinite(value) || value <= 0) return '—';
		return `${value.toFixed(value >= 10 ? 1 : 2)}×`;
	}

	function publishViewport() {
		if (!viewer || holdUrl || !viewer.isOpen()) return;
		const tiled = viewer.world.getItemAt(0);
		if (!tiled) return;
		const center = tiled.viewportToImageCoordinates(viewer.viewport.getCenter(true));
		const bounds = tiled.viewportToImageRectangle(viewer.viewport.getBounds(true));
		const width = viewer.container.clientWidth;
		if (!(bounds.width > 0) || !(width > 0)) return;
		caseState.commitViewport({ x: center.x, y: center.y, zoom: width / bounds.width });
	}

	function schedulePublish() {
		window.clearTimeout(urlTimer);
		urlTimer = window.setTimeout(publishViewport, 80);
	}

	function fitBox(
		target: import('openseadragon').Viewer,
		x: number,
		y: number,
		width: number,
		height: number,
		immediately: boolean
	) {
		const tiled = target.world.getItemAt(0);
		if (!tiled) return;
		const rect = tiled.imageToViewportRectangle(x, y, width, height);
		target.viewport.fitBounds(rect, immediately);
	}

	function fitZoom(
		target: import('openseadragon').Viewer,
		x: number,
		y: number,
		pixelsPerLevel0: number,
		immediately: boolean
	) {
		const size = target.viewport.getContainerSize();
		const width = size.x / pixelsPerLevel0;
		const height = size.y / pixelsPerLevel0;
		fitBox(target, x - width / 2, y - height / 2, width, height, immediately);
	}

	function applyCamera(command: NonNullable<typeof caseState.camera>) {
		if (!viewer) return;
		if (
			command.width != null &&
			command.height != null &&
			command.width > 0 &&
			command.height > 0
		) {
			fitBox(viewer, command.x, command.y, command.width, command.height, false);
			return;
		}
		if (command.zoom != null && command.zoom > 0) {
			fitZoom(viewer, command.x, command.y, command.zoom, false);
			return;
		}
		const tiled = viewer.world.getItemAt(0);
		if (!tiled) return;
		viewer.viewport.panTo(tiled.imageToViewportCoordinates(command.x, command.y), false);
	}

	function applyArrival(arrival: NonNullable<typeof caseState.arrival>) {
		if (!viewer) return;
		const hasPoint = arrival.x != null && arrival.y != null;
		const hasZoom = arrival.zoom != null && arrival.zoom > 0;
		if (hasPoint && hasZoom) {
			fitZoom(viewer, arrival.x ?? 0, arrival.y ?? 0, arrival.zoom ?? 1, true);
		} else if (arrival.patch) {
			const pad = Math.max(arrival.patch.size * 0.5, 64);
			fitBox(
				viewer,
				arrival.patch.x - pad,
				arrival.patch.y - pad,
				arrival.patch.size + pad * 2,
				arrival.patch.size + pad * 2,
				true
			);
		} else if (hasPoint) {
			const tiled = viewer.world.getItemAt(0);
			if (!tiled) return;
			viewer.viewport.panTo(tiled.imageToViewportCoordinates(arrival.x ?? 0, arrival.y ?? 0), true);
		}
		if (!arrival.patch && hasPoint) void caseState.markPatchAt(arrival.x ?? 0, arrival.y ?? 0);
	}

	function onOpen() {
		fetching = false;
		const command = caseState.camera;
		if (
			viewer &&
			command &&
			command.seq !== appliedCamera &&
			command.slideId === caseState.activeSlideId
		) {
			appliedCamera = command.seq;
			applyCamera(command);
		} else if (viewer) {
			const arrival = caseState.consumeArrival();
			if (arrival && arrival.slideId === caseState.activeSlideId) applyArrival(arrival);
		}
		holdUrl = false;
		redraw();
		publishViewport();
	}

	function redraw() {
		if (!viewer || !frame) return;
		const slide = caseState.activeSlide;
		const tiled = viewer.isOpen() ? viewer.world.getItemAt(0) : null;
		const containerWidth = frame.clientWidth;
		const containerHeight = frame.clientHeight;
		if (!slide || !tiled || containerWidth < 2 || containerHeight < 2) return;
		const dpr = window.devicePixelRatio || 1;
		const imageBounds = tiled.viewportToImageRectangle(viewer.viewport.getBounds(true));
		const projection = projectionFromVisibleBounds({
			slideWidth: slide.width,
			slideHeight: slide.height,
			containerWidth,
			containerHeight,
			dpr,
			visible: {
				x: imageBounds.x,
				y: imageBounds.y,
				width: imageBounds.width,
				height: imageBounds.height
			}
		});
		magnification = formatMagnification(slide.magnification * projection.pixelsPerLevel0);
		const bar = scaleBarFor(slide.mpp, projection.pixelsPerLevel0);
		scaleLabel = bar?.label ?? '';
		scalePx = bar?.px ?? 0;
		for (const layer of LAYER_ORDER) {
			const canvas = canvasFor[layer]();
			if (!canvas) continue;
			const context = prepareLayerCanvas(canvas, containerWidth, containerHeight, dpr);
			if (!context || !caseState.layers[layer]) continue;
			for (const draw of caseState.drawersFor(layer)) {
				context.save();
				draw(context, projection);
				context.restore();
			}
			if (layer === 'searchHits')
				drawSearchHitLayer(context, projection, caseState.searchHitMarkers);
			if (layer === 'annotations') {
				drawAnnotationLayer(
					context,
					projection,
					caseState.annotationShapes,
					caseState.draftAnnotationShape
				);
			}
			if (layer === 'selection') {
				const selection = caseState.selection;
				drawSelectionLayer(
					context,
					projection,
					selection && selection.slideId === slide.id
						? selection.kind === 'patch'
							? { kind: 'patch', x: selection.x, y: selection.y, size: selection.size }
							: {
									kind: 'region',
									x: selection.x,
									y: selection.y,
									width: selection.width,
									height: selection.height
								}
						: null,
					dragRect
				);
			}
		}
	}

	function level0FromPointer(event: PointerEvent): { x: number; y: number } | null {
		if (!viewer || !frame || !osdPoint) return null;
		const tiled = viewer.world.getItemAt(0);
		if (!tiled) return null;
		const box = frame.getBoundingClientRect();
		const image = tiled.viewerElementToImageCoordinates(
			new osdPoint(event.clientX - box.left, event.clientY - box.top)
		);
		const slide = caseState.activeSlide;
		if (!slide) return { x: image.x, y: image.y };
		return {
			x: Math.min(slide.width, Math.max(0, image.x)),
			y: Math.min(slide.height, Math.max(0, image.y))
		};
	}

	function normaliseDrag(
		start: { x: number; y: number },
		end: { x: number; y: number }
	): Level0Bounds {
		return {
			x: Math.min(start.x, end.x),
			y: Math.min(start.y, end.y),
			width: Math.abs(end.x - start.x),
			height: Math.abs(end.y - start.y)
		};
	}

	let dragStart: { x: number; y: number } | null = null;

	function onPointerDown(event: PointerEvent) {
		if (caseState.interactionMode === 'pan') return;
		const point = level0FromPointer(event);
		if (!point) return;
		(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
		if (caseState.interactionMode === 'draw-annotation-point') {
			caseState.completeAnnotationDraw({ kind: 'point', x: point.x, y: point.y });
			return;
		}
		dragging = true;
		dragStart = point;
		dragRect = { x: point.x, y: point.y, width: 0, height: 0 };
	}

	function onPointerMove(event: PointerEvent) {
		if (!dragging || !dragStart) return;
		const point = level0FromPointer(event);
		if (!point) return;
		const rect = normaliseDrag(dragStart, point);
		dragRect = rect;
		if (caseState.interactionMode === 'draw-annotation-rect') {
			caseState.draftAnnotationShape = {
				id: 'draft',
				kind: 'rect',
				x: rect.x,
				y: rect.y,
				w: rect.width,
				h: rect.height,
				label: '',
				isOwn: true
			};
		}
	}

	function onPointerUp() {
		if (!dragging || !dragStart || !dragRect) {
			dragging = false;
			dragStart = null;
			return;
		}
		const rect = dragRect;
		dragging = false;
		dragStart = null;
		dragRect = null;
		if (rect.width < 2 && rect.height < 2) {
			caseState.draftAnnotationShape = null;
			return;
		}
		if (caseState.interactionMode === 'select-region') caseState.selectRegion(rect);
		else if (caseState.interactionMode === 'draw-annotation-rect') {
			caseState.completeAnnotationDraw({
				kind: 'rect',
				x: rect.x,
				y: rect.y,
				w: rect.width,
				h: rect.height
			});
		}
	}

	function zoomBy(factor: number) {
		if (!viewer?.viewport) return;
		viewer.viewport.zoomBy(factor);
		viewer.viewport.applyConstraints();
	}

	function toggleRegion() {
		caseState.setInteractionMode(
			caseState.interactionMode === 'select-region' ? 'pan' : 'select-region'
		);
	}

	function findSimilar() {
		const selection = caseState.selection;
		if (!selection) return;
		if (selection.kind === 'patch') {
			caseState.triggerEvidenceSearch({
				kind: 'patch',
				patchId: selection.patchId,
				slideId: selection.slideId,
				x: selection.x,
				y: selection.y,
				size: selection.size
			});
			return;
		}
		caseState.triggerEvidenceSearch({
			kind: 'region',
			slideId: selection.slideId,
			x: selection.x,
			y: selection.y,
			width: selection.width,
			height: selection.height
		});
	}

	function askAboutRegion() {
		const selection = caseState.selection;
		if (!selection) return;
		if (selection.kind === 'patch') {
			caseState.attachToConsult({
				kind: 'region',
				slideId: selection.slideId,
				x: selection.x,
				y: selection.y,
				width: selection.size,
				height: selection.size,
				patchId: selection.patchId
			});
			return;
		}
		caseState.attachToConsult({
			kind: 'region',
			slideId: selection.slideId,
			x: selection.x,
			y: selection.y,
			width: selection.width,
			height: selection.height
		});
	}

	function annotateSelection() {
		const selection = caseState.selection;
		if (!selection) return;
		caseState.triggerAnnotateSelection(
			selection.kind === 'patch'
				? {
						slideId: selection.slideId,
						x: selection.x,
						y: selection.y,
						width: selection.size,
						height: selection.size
					}
				: {
						slideId: selection.slideId,
						x: selection.x,
						y: selection.y,
						width: selection.width,
						height: selection.height
					}
		);
	}

	function retryTiles() {
		const slide = caseState.activeSlide;
		if (!viewer || !slide) return;
		tileError = false;
		tileFailures = 0;
		fetching = true;
		holdUrl = true;
		viewer.open({ tileSource: slide.dzi_url });
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || casePeek.target) return;
		if (caseState.interactionMode !== 'pan') caseState.cancelInteractionMode();
	}

	$effect(() => {
		if (!fetching || tileError) {
			showFetching = false;
			return;
		}
		const timer = window.setTimeout(() => {
			showFetching = true;
		}, 200);
		return () => window.clearTimeout(timer);
	});

	$effect(() => {
		depend(viewerEpoch);
		const drawing = caseState.interactionMode !== 'pan';
		if (!viewer) return;
		const gestures = viewer.gestureSettingsByDeviceType('mouse');
		gestures.dragToPan = !drawing;
		const touch = viewer.gestureSettingsByDeviceType('touch');
		touch.dragToPan = !drawing;
		const nav = viewer as import('openseadragon').Viewer & {
			panHorizontal: boolean;
			panVertical: boolean;
		};
		nav.panHorizontal = !drawing;
		nav.panVertical = !drawing;
	});

	$effect(() => {
		depend(viewerEpoch);
		const phase = caseState.slidePhase;
		const slide = caseState.activeSlide;
		if (!viewer) return;
		if (phase !== 'ready' || !slide) {
			if (openedSlideId && viewer.isOpen()) viewer.close();
			openedSlideId = '';
			fetching = false;
			return;
		}
		if (openedSlideId === slide.id) return;
		openedSlideId = slide.id;
		tileError = false;
		tileFailures = 0;
		fetching = true;
		holdUrl = true;
		viewer.open({ tileSource: slide.dzi_url });
	});

	$effect(() => {
		const command = caseState.camera;
		depend(viewerEpoch);
		if (!viewer || !command || command.seq === appliedCamera) return;
		if (!viewer.isOpen() || caseState.activeSlide?.id !== command.slideId) return;
		appliedCamera = command.seq;
		applyCamera(command);
	});

	$effect(() => {
		depend(
			viewerEpoch,
			caseState.selection,
			caseState.layers.heatmap,
			caseState.layers.searchHits,
			caseState.layers.annotations,
			caseState.layers.selection,
			caseState.searchHitMarkers,
			caseState.annotationShapes,
			caseState.draftAnnotationShape,
			caseState.layerVersion,
			dragRect
		);
		redraw();
	});

	onMount(() => {
		let cancelled = false;
		let observer: ResizeObserver | null = null;
		const frameEl = frame;
		void (async () => {
			const imported = await import('openseadragon');
			const createViewer = imported.default;
			osdPoint = createViewer.Point;
			if (cancelled || !host) return;
			const userId = getActingUserId();
			const instance = createViewer({
				element: host,
				showNavigator: true,
				navigatorAutoFade: false,
				navigatorPosition: 'TOP_RIGHT',
				navigatorHeight: 120,
				navigatorWidth: 180,
				navigatorBackground: '#14191d',
				navigatorBorderColor: 'rgba(255, 255, 255, 0.35)',
				navigatorDisplayRegionColor: '#f3d38a',
				showNavigationControl: false,
				showZoomControl: false,
				showHomeControl: false,
				showFullPageControl: false,
				gestureSettingsMouse: {
					scrollToZoom: true,
					clickToZoom: false,
					dblClickToZoom: true,
					dragToPan: true,
					pinchToZoom: true
				},
				gestureSettingsTouch: {
					pinchToZoom: true,
					clickToZoom: false,
					dblClickToZoom: true,
					dragToPan: true
				},
				minZoomImageRatio: 1,
				maxZoomPixelRatio: 1,
				visibilityRatio: 0.25,
				constrainDuringPan: true,
				placeholderFillStyle: '#14191d',
				animationTime: 0.35,
				timeout: 120000,
				tileRetryMax: 2,
				imageLoaderLimit: 8,
				ajaxHeaders: userId ? { [ACTING_USER_HEADER]: userId } : undefined
			});
			if (cancelled) {
				instance.destroy();
				return;
			}
			viewer = instance;
			instance.addHandler('open', onOpen);
			instance.addHandler('open-failed', () => {
				tileError = true;
				fetching = false;
				holdUrl = false;
			});
			instance.addHandler('tile-load-failed', () => {
				tileFailures += 1;
				if (tileFailures >= 4) {
					tileError = true;
					fetching = false;
				}
			});
			instance.addHandler('tile-loaded', () => {
				tileFailures = 0;
				fetching = false;
				tileError = false;
			});
			instance.addHandler('animation', redraw);
			instance.addHandler('update-viewport', redraw);
			instance.addHandler('resize', redraw);
			instance.addHandler('animation-finish', () => {
				if (!holdUrl) schedulePublish();
			});
			instance.addHandler('canvas-click', (event) => {
				if (!event.quick || caseState.interactionMode !== 'pan' || !viewer) return;
				const tiled = viewer.world.getItemAt(0);
				if (!tiled) return;
				const image = tiled.viewerElementToImageCoordinates(event.position);
				const bounds = tiled.viewportToImageRectangle(viewer.viewport.getBounds(true));
				const pixelsPerLevel0 = viewer.container.clientWidth / Math.max(bounds.width, 0.0001);
				const slop = 12 / Math.max(pixelsPerLevel0, 0.0001);
				const note = annotationAtPoint(caseState.annotationShapes, image.x, image.y, slop);
				if (note && caseState.onSelectAnnotation) {
					caseState.onSelectAnnotation(note.id);
					return;
				}
				const hit = searchHitAtPoint(caseState.searchHitMarkers, image.x, image.y);
				if (hit && caseState.onSearchHitClick) {
					caseState.onSearchHitClick(hit);
					return;
				}
				void caseState.selectPatchAt(image.x, image.y);
			});
			if (frameEl) {
				observer = new ResizeObserver(() => {
					instance.forceResize();
					redraw();
				});
				observer.observe(frameEl);
			}
			viewerEpoch += 1;
		})();
		return () => {
			cancelled = true;
			window.clearTimeout(urlTimer);
			observer?.disconnect();
			viewer?.destroy();
			viewer = null;
		};
	});

	const ready = $derived(
		caseState.slidePhase === 'ready' && caseState.activeSlide?.status === 'ready'
	);
	const notReady = $derived(caseState.slidePhase === 'not-ready' && caseState.activeSlide);
	const slideProblem = $derived(
		caseState.slidePhase === 'missing' || caseState.slidePhase === 'error'
	);
</script>

<svelte:window onkeydown={onKeydown} />

<section class="viewer-shell" aria-label="Whole slide viewer">
	<div class="viewer" bind:this={frame}>
		<div class="osd" bind:this={host}></div>
		<canvas bind:this={heatmapCanvas} class="overlay-canvas heatmap"></canvas>
		<canvas bind:this={searchCanvas} class="overlay-canvas hits"></canvas>
		<canvas bind:this={annotationCanvas} class="overlay-canvas notes"></canvas>
		<canvas bind:this={selectionCanvas} class="overlay-canvas selection"></canvas>
		{#if caseState.interactionMode !== 'pan'}
			<div
				class="gesture-layer"
				role="application"
				aria-label={caseState.interactionMode === 'select-region'
					? 'Drag to select a region'
					: 'Drag to draw an annotation'}
				onpointerdown={onPointerDown}
				onpointermove={onPointerMove}
				onpointerup={onPointerUp}
				onpointercancel={onPointerUp}
			></div>
		{/if}

		{#if showFetching && caseState.activeSlide}
			<div class="cover">
				{#if caseState.activeSlide.thumbnail_url}
					<img
						src={caseState.activeSlide.thumbnail_url}
						alt="Slide thumbnail while tiles are fetched"
					/>
				{/if}
				<div class="cover-copy">
					<progress aria-label="Fetching slide"></progress>
					<Typography style="label" tone="inverse">Fetching slide</Typography>
					<Typography style="small" tone="inverse">
						The file is loading into the viewer. This can take a moment the first time.
					</Typography>
				</div>
			</div>
		{/if}

		{#if tileError}
			<div class="cover message">
				<StateMessage
					tone="danger"
					title="This slide could not be read"
					description="Tile loading failed. Retry the image; the side panel is unchanged."
					action="Retry"
					onaction={retryTiles}
				/>
			</div>
		{/if}

		{#if notReady && caseState.activeSlide}
			{@const copy = slideStatusCopy(caseState.activeSlide.status)}
			<div class="cover message">
				<StateMessage
					tone="warning"
					title={copy.title}
					description={copy.description}
					action="Check again"
					onaction={() => caseState.reloadSlide()}
				/>
			</div>
		{/if}

		{#if slideProblem}
			<div class="cover message">
				<StateMessage
					tone="danger"
					title={caseState.slidePhase === 'missing' ? 'Slide not found' : 'Slide unavailable'}
					description={caseState.slideError ?? 'The slide could not be loaded.'}
					action="Retry"
					onaction={() => caseState.reloadSlide()}
				/>
			</div>
		{/if}

		{#if caseState.slidePhase === 'loading'}
			{@const thumb = caseState.caseDetail?.slides.find(
				(slide) => slide.id === caseState.activeSlideId
			)?.thumbnail_url}
			<div class="cover message">
				{#if thumb}
					<img class="thumb-ghost" src={thumb} alt="" />
				{/if}
				<Typography style="label" tone="inverse">Loading slide</Typography>
			</div>
		{/if}

		{#if ready && !tileError}
			<div class="viewer-controls">
				<Button
					variant="secondary"
					icon="zoom-in"
					iconOnly
					ariaLabel="Zoom in"
					onclick={() => zoomBy(1.4)}
				/>
				<Button
					variant="secondary"
					icon="zoom-out"
					iconOnly
					ariaLabel="Zoom out"
					onclick={() => zoomBy(1 / 1.4)}
				/>
				<Button
					variant={caseState.interactionMode === 'select-region' ? 'primary' : 'secondary'}
					icon="grid"
					iconOnly
					ariaLabel={caseState.interactionMode === 'select-region'
						? 'Stop selecting a region'
						: 'Select region'}
					onclick={toggleRegion}
				/>
			</div>

			<div class="viewer-meta">
				<Badge tone="neutral"><span aria-live="polite">{magnification}</span></Badge>
				{#if scaleLabel}
					<div class="scale">
						<span style:width="{scalePx}px"></span>
						<Typography style="small" tone="inverse">{scaleLabel}</Typography>
					</div>
				{/if}
			</div>

			<div class="layers-popover">
				<div class="layers-title">
					<Icon name="layers" size="sm" />
					<Typography style="label" tone="inverse">Layers</Typography>
				</div>
				<CheckField bind:checked={caseState.layers.heatmap}>
					<span class="layer-swatch heatmap"></span>
					<Typography as="span" style="small" tone="inverse">Heatmap</Typography>
				</CheckField>
				<CheckField bind:checked={caseState.layers.searchHits}>
					<span class="layer-swatch searchHits"></span>
					<Typography as="span" style="small" tone="inverse">Search hits</Typography>
				</CheckField>
				<CheckField bind:checked={caseState.layers.annotations}>
					<span class="layer-swatch annotations"></span>
					<Typography as="span" style="small" tone="inverse">Annotations</Typography>
				</CheckField>
				<CheckField bind:checked={caseState.layers.selection}>
					<span class="layer-swatch selection"></span>
					<Typography as="span" style="small" tone="inverse">Selection</Typography>
				</CheckField>
			</div>

			{#if caseState.selection}
				<div class="selection-actions">
					<Button variant="primary" size="sm" icon="evidence" onclick={findSimilar}>
						Find similar tissue
					</Button>
					<Button variant="secondary" size="sm" icon="spark" onclick={askAboutRegion}>
						Ask about this region
					</Button>
					<Button variant="secondary" size="sm" icon="annotation" onclick={annotateSelection}>
						Annotate
					</Button>
					<Button
						variant="ghost"
						size="sm"
						icon="close"
						iconOnly
						ariaLabel="Clear selection"
						onclick={() => caseState.clearSelection()}
					/>
				</div>
			{/if}
		{/if}
	</div>
</section>

<style>
	.viewer-shell,
	.viewer {
		width: 100%;
		height: 100%;
		min-width: 0;
		background: var(--color-viewer);
	}
	.viewer {
		position: relative;
		min-height: 100%;
		overflow: hidden;
	}
	.osd,
	.overlay-canvas,
	.gesture-layer,
	.cover {
		position: absolute;
		inset: 0;
	}
	.osd {
		z-index: 0;
	}
	.osd :global(.openseadragon-container) {
		background: var(--color-viewer);
	}
	.overlay-canvas {
		z-index: 1;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}
	.overlay-canvas.hits {
		z-index: 2;
	}
	.overlay-canvas.notes {
		z-index: 3;
	}
	.overlay-canvas.selection {
		z-index: 4;
	}
	.gesture-layer {
		z-index: 5;
		cursor: crosshair;
		touch-action: none;
	}
	.cover {
		z-index: 6;
		display: grid;
		place-items: center;
		background: var(--color-viewer);
	}
	.cover img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: contain;
		opacity: 0.9;
	}
	.cover-copy {
		position: relative;
		display: grid;
		justify-items: center;
		gap: var(--space-2);
		max-width: 22rem;
		padding: var(--space-4);
		text-align: center;
	}
	.cover.message {
		background:
			radial-gradient(circle at 50% 40%, var(--color-viewer-radial), transparent 55%),
			var(--color-viewer);
	}
	.thumb-ghost {
		opacity: 0.35;
	}
	progress {
		width: 12rem;
		height: 0.4rem;
		accent-color: var(--color-action);
	}
	.viewer-controls,
	.viewer-meta,
	.layers-popover,
	.selection-actions {
		position: absolute;
		z-index: 7;
	}
	.viewer-controls {
		top: var(--space-4);
		left: var(--space-4);
		display: grid;
		gap: var(--space-1);
	}
	.viewer-meta {
		left: var(--space-4);
		bottom: var(--space-4);
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-2);
		border-radius: var(--radius-md);
		background: var(--color-viewer-panel);
	}
	.scale {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.scale span {
		height: var(--space-2);
		border: solid var(--color-text-inverse);
		border-width: 0 var(--border-width) var(--border-width);
	}
	.layers-popover {
		top: 9.5rem;
		right: var(--space-4);
		display: grid;
		gap: var(--space-2);
		width: 11.5rem;
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-md);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
	}
	.layers-title {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.layer-swatch {
		width: var(--space-3);
		height: var(--space-3);
		border-radius: var(--radius-xs);
		background: var(--color-heatmap-high);
	}
	.layer-swatch.searchHits {
		border-radius: var(--radius-pill);
		background: var(--color-action);
	}
	.layer-swatch.annotations {
		background: transparent;
		border: var(--border-width) solid var(--color-info-soft);
	}
	.layer-swatch.selection {
		background: transparent;
		border: var(--border-width) solid #f3d38a;
	}
	.selection-actions {
		left: 50%;
		bottom: var(--space-6);
		display: flex;
		gap: var(--space-2);
		padding: var(--space-2);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-lg);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
		transform: translateX(-50%);
	}
	@media (max-width: 760px) {
		.layers-popover {
			display: none;
		}
		.selection-actions {
			left: var(--space-3);
			right: var(--space-3);
			overflow-x: auto;
			transform: none;
		}
	}
</style>
