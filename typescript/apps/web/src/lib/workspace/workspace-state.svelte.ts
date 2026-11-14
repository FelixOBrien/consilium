import { getContext, setContext } from 'svelte';
import { SvelteMap, SvelteSet, SvelteURL, SvelteURLSearchParams } from 'svelte/reactivity';
import { api } from '#lib/api/client.js';
import {
	clampLevel0Rect,
	type LayerDrawer,
	type LayerId,
	type Level0Bounds,
	type ViewerAnnotationShape,
	type ViewerSearchHit
} from './overlay-layers.js';
import {
	formatLevel0,
	formatZoom,
	isPanelId,
	readViewportQuery,
	withViewportQuery,
	type PanelId,
	type ViewportQueryPatch
} from './viewport-url.js';

type Schemas = import('#lib/api/schema.js').components['schemas'];

/** Generated case payload. Alias only — the shape lives in the OpenAPI client. */
export type CaseDetail = Schemas['CaseDetail'];
/** Generated slide payload (`SlideDetail`). */
export type Slide = Schemas['SlideDetail'];
export type PatchRef = Schemas['PatchRef'];

export type SlideSelection =
	| {
			kind: 'patch';
			patchId: string;
			slideId: string;
			x: number;
			y: number;
			size: number;
	  }
	| {
			kind: 'region';
			slideId: string;
			x: number;
			y: number;
			width: number;
			height: number;
	  };

export type InteractionMode =
	'pan' | 'select-region' | 'draw-annotation-rect' | 'draw-annotation-point';

export type EvidenceHandoff =
	| {
			kind: 'patch';
			patchId: string;
			slideId: string;
			x: number;
			y: number;
			size: number;
	  }
	| {
			kind: 'region';
			slideId: string;
			x: number;
			y: number;
			width: number;
			height: number;
	  }
	| { kind: 'report_text'; text: string };

export type PendingEvidenceIntent = EvidenceHandoff & { seq: number };

export type ConsultRegionAttachment = {
	kind: 'region';
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
	patchId?: string;
	label?: string;
};

export type ConsultCasesAttachment = {
	kind: 'cases';
	caseIds: string[];
};

export type ConsultHandoff = ConsultRegionAttachment | ConsultCasesAttachment;

export type PendingAnnotationRegion = {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
	seq: number;
};

export type HeatmapPhraseRequest = {
	phrase: string;
	negativePhrase?: string;
	seq: number;
};

export type AnnotationGeometry =
	| { kind: 'rect'; x: number; y: number; w: number; h: number }
	| { kind: 'point'; x: number; y: number };

export type CameraCommand = {
	seq: number;
	slideId: string;
	x: number;
	y: number;
	width?: number;
	height?: number;
	zoom?: number;
};

export type Arrival = {
	slideId: string;
	x: number | null;
	y: number | null;
	zoom: number | null;
	patch: PatchRef | null;
	consumed: boolean;
};

export type FlyToLevel0 = {
	slideId?: string;
	x: number;
	y: number;
	width?: number;
	height?: number;
	zoom?: number;
	markPatch?: { id?: string; x: number; y: number; size: number };
};

export type BrowserLocation = {
	href: () => string;
	replace: (href: string) => void;
};

const CASE_CONTEXT = Symbol('case-view');

function browserLocation(): BrowserLocation {
	return {
		href: () => window.location.href,
		replace: (href) => history.replaceState(history.state, '', href)
	};
}

/**
 * Shared case-view state. Panels and overlays read it with
 * `getWorkspaceContext()` and take no props from the page or the viewer. // pragma: allowlist secret
 */
export class WorkspaceState /* pragma: allowlist secret */ {
	caseId = $state('');
	caseDetail = $state<CaseDetail | null>(null);
	casePhase = $state<'loading' | 'ready' | 'not-found' | 'error'>('loading');
	caseError = $state<string | null>(null);

	activeSlideId = $state<string | null>(null);
	activeSlide = $state<Slide | null>(null);
	slidePhase = $state<'idle' | 'loading' | 'ready' | 'not-ready' | 'missing' | 'error'>('idle');
	slideError = $state<string | null>(null);

	activePanel = $state<PanelId>('report');
	panelVisible = $state(true);

	layers = $state<Record<LayerId, boolean>>({
		heatmap: true,
		searchHits: true,
		annotations: true,
		selection: true
	});
	/** Bumped when a drawer is registered or a layer asks to redraw. */
	layerVersion = $state(0);

	searchHitMarkers = $state<ViewerSearchHit[]>([]);
	onSearchHitClick: ((hit: ViewerSearchHit) => void) | null = null;

	annotationShapes = $state<ViewerAnnotationShape[]>([]);
	draftAnnotationShape = $state<ViewerAnnotationShape | null>(null);
	onSelectAnnotation: ((id: string) => void) | null = null;

	selection = $state<SlideSelection | null>(null);
	interactionMode = $state<InteractionMode>('pan');

	pendingEvidenceIntent = $state<PendingEvidenceIntent | null>(null);
	consultRegionAttachment = $state<ConsultRegionAttachment | null>(null);
	consultCasesAttachment = $state<ConsultCasesAttachment | null>(null);
	pendingAnnotationRegion = $state<PendingAnnotationRegion | null>(null);
	/**
	 * Phrase the report panel asked to shade. `heatmapRequest` is the same value.
	 * Null clears the overlay. Cleared when the slide changes.
	 */
	heatmapPhraseRequest = $state<HeatmapPhraseRequest | null>(null);

	camera = $state<CameraCommand | null>(null);
	arrival = $state<Arrival | null>(null);

	#location: BrowserLocation;
	#loadToken = 0;
	#slideToken = 0;
	#hitToken = 0;
	#seq = 0;
	#cameraSeq = 0;
	#openedCaseId = '';
	#drawers = new SvelteMap<LayerId, SvelteSet<LayerDrawer>>();
	#onDrawComplete: ((geom: AnnotationGeometry) => void) | null = null;
	#onDrawCancel: (() => void) | null = null;

	constructor(location: BrowserLocation = browserLocation()) {
		this.#location = location;
	}

	/** Same object as `heatmapPhraseRequest`, the name cleared with the slide. */
	get heatmapRequest(): HeatmapPhraseRequest | null {
		return this.heatmapPhraseRequest;
	}

	async openCase(caseId: string, params: { get(name: string): string | null }): Promise<void> {
		if (this.#openedCaseId === caseId && this.casePhase !== 'error') return;
		const token = ++this.#loadToken;
		this.#openedCaseId = caseId;
		this.caseId = caseId;
		this.casePhase = 'loading';
		this.caseError = null;
		this.caseDetail = null;
		this.activeSlide = null;
		this.activeSlideId = null;
		this.slidePhase = 'idle';
		this.slideError = null;
		this.clearSlideScopedState();
		this.arrival = null;
		this.camera = null;

		const query = readViewportQuery(params);
		this.activePanel = query.panel ?? 'report';
		this.panelVisible = true;

		const result = await api.GET('/api/cases/{case_id}', {
			params: { path: { case_id: caseId } }
		});
		if (token !== this.#loadToken) return;
		if (result.response.status === 404) {
			this.casePhase = 'not-found';
			return;
		}
		if (!result.data) {
			this.casePhase = 'error';
			this.caseError = 'The case could not be loaded.';
			return;
		}

		const detail = result.data;
		this.caseDetail = detail;
		this.casePhase = 'ready';

		let patch: PatchRef | null = null;
		if (query.patch && Number.isInteger(Number(query.patch))) {
			const patchResult = await api.GET('/api/patches/{patch_id}', {
				params: { path: { patch_id: Number(query.patch) } }
			});
			if (token !== this.#loadToken) return;
			if (patchResult.data?.case_id === detail.id) patch = patchResult.data;
		}

		const requested = patch?.slide_id ?? query.slide;
		const slideId =
			detail.slides.find((slide) => slide.id === requested)?.id ?? detail.slides[0]?.id ?? null;
		if (!slideId) {
			this.slidePhase = 'missing';
			this.#write({ panel: this.activePanel });
			return;
		}

		this.arrival = {
			slideId,
			x: query.x,
			y: query.y,
			zoom: query.zoom,
			patch,
			consumed: false
		};
		if (patch) {
			this.selection = {
				kind: 'patch',
				patchId: String(patch.id),
				slideId: patch.slide_id,
				x: patch.x,
				y: patch.y,
				size: patch.size
			};
		}
		this.activeSlideId = slideId;
		this.#write({ slide: slideId, panel: this.activePanel });
		await this.#fetchSlide(slideId);
	}

	retryCase(): void {
		const caseId = this.caseId;
		if (!caseId) return;
		this.#openedCaseId = '';
		const params = new SvelteURLSearchParams(new SvelteURL(this.#location.href()).search);
		void this.openCase(caseId, params);
	}

	selectSlide(slideId: string): void {
		if (!this.caseDetail?.slides.some((slide) => slide.id === slideId)) return;
		if (slideId === this.activeSlideId && (this.activeSlide || this.slidePhase === 'loading'))
			return;
		this.clearSlideScopedState();
		this.arrival = null;
		this.camera = null;
		this.activeSlideId = slideId;
		this.activeSlide = null;
		this.#write({ slide: slideId, x: null, y: null, zoom: null, patch: null });
		void this.#fetchSlide(slideId);
	}

	reloadSlide(): void {
		const slideId = this.activeSlideId;
		if (!slideId) return;
		void this.#fetchSlide(slideId);
	}

	openPanel(panel: PanelId): void {
		this.activePanel = panel;
		this.panelVisible = true;
		this.#write({ panel });
	}

	hidePanel(): void {
		this.panelVisible = false;
	}

	showPanel(): void {
		this.panelVisible = true;
	}

	setLayerVisible(layer: LayerId, visible: boolean): void {
		this.layers[layer] = visible;
	}

	toggleLayer(layer: LayerId): void {
		this.layers[layer] = !this.layers[layer];
	}

	registerLayerDrawer(layer: LayerId, draw: LayerDrawer): () => void {
		let drawers = this.#drawers.get(layer);
		if (!drawers) {
			drawers = new SvelteSet();
			this.#drawers.set(layer, drawers);
		}
		drawers.add(draw);
		this.layerVersion += 1;
		return () => {
			drawers.delete(draw);
			this.layerVersion += 1;
		};
	}

	drawersFor(layer: LayerId): LayerDrawer[] {
		return [...(this.#drawers.get(layer) ?? [])];
	}

	invalidateLayer(layer: LayerId): void {
		void layer;
		this.layerVersion += 1;
	}

	setSearchHitMarkers(hits: ViewerSearchHit[]): void {
		this.searchHitMarkers = hits;
	}

	setAnnotationShapes(shapes: ViewerAnnotationShape[]): void {
		this.annotationShapes = shapes;
	}

	clearSelection(): void {
		this.selection = null;
	}

	async selectPatchAt(x: number, y: number): Promise<void> {
		const slideId = this.activeSlideId;
		if (!slideId || this.interactionMode !== 'pan') return;
		await this.#hitTest(slideId, x, y, true);
	}

	/** Outline the patch under an arrived coordinate. A miss leaves the current selection. */
	async markPatchAt(x: number, y: number): Promise<void> {
		const slideId = this.activeSlideId;
		if (!slideId) return;
		await this.#hitTest(slideId, x, y, false);
	}

	selectRegion(rect: Level0Bounds): void {
		const slide = this.activeSlide;
		if (!slide) return;
		const clamped = clampLevel0Rect(rect, slide.width, slide.height);
		if (clamped.width < 1 || clamped.height < 1) return;
		this.selection = { kind: 'region', slideId: slide.id, ...clamped };
	}

	setInteractionMode(mode: 'pan' | 'select-region'): void {
		this.#cancelDraw(true);
		this.interactionMode = mode;
	}

	startAnnotationDraw(
		kind: 'rect' | 'point',
		onComplete: (geom: AnnotationGeometry) => void,
		onCancel?: () => void
	): void {
		this.#cancelDraw(true);
		this.interactionMode = kind === 'rect' ? 'draw-annotation-rect' : 'draw-annotation-point';
		this.#onDrawComplete = onComplete;
		this.#onDrawCancel = onCancel ?? null;
	}

	completeAnnotationDraw(geom: AnnotationGeometry): void {
		const done = this.#onDrawComplete;
		this.#onDrawComplete = null;
		this.#onDrawCancel = null;
		this.draftAnnotationShape = null;
		this.interactionMode = 'pan';
		done?.(geom);
	}

	cancelInteractionMode(): void {
		this.#cancelDraw(true);
		this.interactionMode = 'pan';
	}

	flyToLevel0(opts: FlyToLevel0): void {
		const slideId = opts.slideId ?? this.activeSlideId;
		if (!slideId) return;
		if (opts.slideId && opts.slideId !== this.activeSlideId) {
			if (!this.caseDetail?.slides.some((slide) => slide.id === opts.slideId)) return;
			this.selectSlide(opts.slideId);
		}
		if (opts.markPatch) {
			this.selection = {
				kind: 'patch',
				patchId: opts.markPatch.id ?? '',
				slideId,
				x: opts.markPatch.x,
				y: opts.markPatch.y,
				size: opts.markPatch.size
			};
		}
		this.camera = {
			seq: ++this.#cameraSeq,
			slideId,
			x: opts.x,
			y: opts.y,
			width: opts.width,
			height: opts.height,
			zoom: opts.zoom
		};
	}

	consumeArrival(): Arrival | null {
		const arrival = this.arrival;
		if (!arrival || arrival.consumed) return null;
		this.arrival = { ...arrival, consumed: true };
		return arrival;
	}

	commitViewport(view: { x: number; y: number; zoom: number }): void {
		if (!this.activeSlideId) return;
		if (!Number.isFinite(view.x) || !Number.isFinite(view.y) || !(view.zoom > 0)) return;
		this.#write({
			slide: this.activeSlideId,
			x: formatLevel0(view.x),
			y: formatLevel0(view.y),
			zoom: formatZoom(view.zoom),
			patch: null
		});
	}

	triggerEvidenceSearch(intent: EvidenceHandoff): void {
		this.pendingEvidenceIntent = { ...intent, seq: this.#nextSeq() };
		this.openPanel('evidence');
	}

	attachToConsult(attachment: ConsultHandoff): void {
		if (attachment.kind === 'region') this.consultRegionAttachment = attachment;
		else this.consultCasesAttachment = attachment;
		this.openPanel('consult');
	}

	triggerAnnotateSelection(region: {
		slideId: string;
		x: number;
		y: number;
		width: number;
		height: number;
	}): void {
		this.pendingAnnotationRegion = { ...region, seq: this.#nextSeq() };
		this.openPanel('annotations');
	}

	requestHeatmapPhrase(phrase: string | null, negativePhrase?: string): void {
		this.heatmapPhraseRequest = phrase ? { phrase, negativePhrase, seq: this.#nextSeq() } : null;
	}

	clearSlideScopedState(): void {
		this.selection = null;
		this.searchHitMarkers = [];
		this.draftAnnotationShape = null;
		this.heatmapPhraseRequest = null;
		this.#cancelDraw(false);
		this.interactionMode = 'pan';
	}

	async #fetchSlide(slideId: string): Promise<void> {
		const token = ++this.#slideToken;
		const caseToken = this.#loadToken;
		this.slidePhase = 'loading';
		this.slideError = null;
		const result = await api.GET('/api/slides/{slide_id}', {
			params: { path: { slide_id: slideId } }
		});
		if (token !== this.#slideToken || caseToken !== this.#loadToken) return;
		if (this.activeSlideId !== slideId) return;
		if (result.response.status === 404) {
			this.activeSlide = null;
			this.slidePhase = 'missing';
			this.slideError = 'This slide was not found.';
			return;
		}
		if (!result.data) {
			this.activeSlide = null;
			this.slidePhase = 'error';
			this.slideError = 'The slide could not be loaded.';
			return;
		}
		this.activeSlide = result.data;
		this.slidePhase = result.data.status === 'ready' ? 'ready' : 'not-ready';
	}

	async #hitTest(slideId: string, x: number, y: number, clearOnMiss: boolean): Promise<void> {
		const token = ++this.#hitToken;
		const result = await api.GET('/api/slides/{slide_id}/patches/at', {
			params: {
				path: { slide_id: slideId },
				query: { x: Math.round(x), y: Math.round(y) }
			}
		});
		if (token !== this.#hitToken || this.activeSlideId !== slideId) return;
		if (result.response.status === 404) {
			if (clearOnMiss) this.selection = null;
			return;
		}
		if (!result.data) return;
		const patch = result.data;
		this.selection = {
			kind: 'patch',
			patchId: String(patch.id),
			slideId: patch.slide_id,
			x: patch.x,
			y: patch.y,
			size: patch.size
		};
	}

	#cancelDraw(notify: boolean): void {
		const cancel = this.#onDrawCancel;
		this.#onDrawComplete = null;
		this.#onDrawCancel = null;
		this.draftAnnotationShape = null;
		if (notify) cancel?.();
	}

	#nextSeq(): number {
		this.#seq += 1;
		return this.#seq;
	}

	#write(changes: ViewportQueryPatch): void {
		const current = new SvelteURL(this.#location.href());
		const next = withViewportQuery(current, changes);
		const href = `${next.pathname}${next.search}${next.hash}`;
		const now = `${current.pathname}${current.search}${current.hash}`;
		if (href !== now) this.#location.replace(href);
	}
}

export function setWorkspaceContext /* pragma: allowlist secret */(
	state: WorkspaceState /* pragma: allowlist secret */
): void {
	setContext(CASE_CONTEXT, state);
}

export function getWorkspaceContext(): WorkspaceState /* pragma: allowlist secret */ {
	const state = getContext<WorkspaceState /* pragma: allowlist secret */ | undefined>(CASE_CONTEXT);
	if (!state) {
		throw new Error('Case state is not available. Mount this inside the case page.');
	}
	return state;
}

export { isPanelId, type PanelId };
