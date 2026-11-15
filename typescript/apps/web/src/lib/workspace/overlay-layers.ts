/**
 * Overlay layers for the case viewer.
 *
 * Four canvases sit above the OpenSeadragon tiles. Each layer is toggled on
 * its own and none of them change the others. Stack order, bottom to top:
 *
 * 1. `heatmap` — phrase-to-patch similarity (SKO-275)
 * 2. `searchHits` — evidence markers on this slide (SKO-278)
 * 3. `annotations` — saved marks (SKO-283)
 * 4. `selection` — the patch or region chosen here (SKO-270)
 *
 * Drawers receive level-0 slide pixels, the same space as `patch.x`,
 * `patch.y` and `patch.size`. `ViewportProjection` converts those pixels to
 * CSS pixels in the viewer element. The viewer sizes each canvas with
 * `devicePixelRatio` and scales the context, so a drawer paints in CSS pixels
 * and stays aligned with the tissue at every zoom.
 *
 * Register a drawer from a panel with `WorkspaceState.registerLayerDrawer`. // pragma: allowlist secret
 * Call `invalidateLayer` when the drawing inputs change. The viewer also
 * paints the declarative `searchHitMarkers`, `annotationShapes` and
 * `selection` for those layers, so a panel can use either the drawer or the
 * marker list.
 *
 * Example — outline the patch grid that intersects the viewport:
 *
 * ```ts
 * const unregister = caseState.registerLayerDrawer('heatmap', (ctx, proj) => {
 *   drawVisiblePatchGrid(ctx, proj, patchSize);
 * });
 * ```
 *
 * `unregister()` removes that drawer. `zoom` in the page URL is CSS pixels
 * per level-0 pixel (`pixelsPerLevel0`), which is what this projection reports.
 */

export const LAYER_ORDER = ['heatmap', 'searchHits', 'annotations', 'selection'] as const;

export type LayerId = (typeof LAYER_ORDER)[number];

export type Level0Point = { x: number; y: number };

export type Level0Bounds = { x: number; y: number; width: number; height: number };

export type ViewportProjection = {
	slideWidth: number;
	slideHeight: number;
	containerWidth: number;
	containerHeight: number;
	dpr: number;
	/** CSS pixels per level-0 pixel. This is the URL `zoom` value. */
	pixelsPerLevel0: number;
	level0ToViewer(x: number, y: number): Level0Point;
	viewerToLevel0(vx: number, vy: number): Level0Point;
	visibleLevel0Bounds: Level0Bounds;
};

export type LayerDrawer = (ctx: CanvasRenderingContext2D, proj: ViewportProjection) => void;

export type ViewerSearchHit = {
	id: string;
	x: number;
	y: number;
	width: number;
	height: number;
	rank?: number;
	label?: string;
};

export type ViewerAnnotationShape = {
	id: string;
	kind: 'rect' | 'point';
	x: number;
	y: number;
	w?: number;
	h?: number;
	label: string;
	isOwn: boolean;
	selected?: boolean;
};

export type SelectionGeometry =
	| { kind: 'patch'; x: number; y: number; size: number }
	| { kind: 'region'; x: number; y: number; width: number; height: number };

const SELECTION_STROKE = '#f3d38a';
const HIT_STROKE = '#b7b0f2';
const NOTE_OWN = '#9fd0ef';
const NOTE_OTHER = '#d7dee4';
const INK = '#14191d';

export function isLayerId(value: string): value is LayerId {
	return (LAYER_ORDER as readonly string[]).includes(value);
}

export function projectionFromVisibleBounds(input: {
	slideWidth: number;
	slideHeight: number;
	containerWidth: number;
	containerHeight: number;
	dpr: number;
	visible: Level0Bounds;
}): ViewportProjection {
	const visible = { ...input.visible };
	const widthScale = visible.width > 0 ? input.containerWidth / visible.width : 0;
	const heightScale = visible.height > 0 ? input.containerHeight / visible.height : 0;
	return {
		slideWidth: input.slideWidth,
		slideHeight: input.slideHeight,
		containerWidth: input.containerWidth,
		containerHeight: input.containerHeight,
		dpr: input.dpr,
		pixelsPerLevel0: widthScale,
		visibleLevel0Bounds: visible,
		level0ToViewer(x, y) {
			return {
				x: (x - visible.x) * widthScale,
				y: (y - visible.y) * heightScale
			};
		},
		viewerToLevel0(vx, vy) {
			return {
				x: widthScale === 0 ? visible.x : visible.x + vx / widthScale,
				y: heightScale === 0 ? visible.y : visible.y + vy / heightScale
			};
		}
	};
}

/** Level-0 rectangle centred on a point at a known CSS-pixels-per-pixel zoom. */
export function visibleBoundsAround(
	center: Level0Point,
	pixelsPerLevel0: number,
	containerWidth: number,
	containerHeight: number
): Level0Bounds {
	const safe = pixelsPerLevel0 > 0 ? pixelsPerLevel0 : 1;
	const width = containerWidth / safe;
	const height = containerHeight / safe;
	return {
		x: center.x - width / 2,
		y: center.y - height / 2,
		width,
		height
	};
}

export function clampLevel0Rect(
	rect: Level0Bounds,
	slideWidth: number,
	slideHeight: number
): Level0Bounds {
	const left = clamp(Math.min(rect.x, rect.x + rect.width), 0, slideWidth);
	const top = clamp(Math.min(rect.y, rect.y + rect.height), 0, slideHeight);
	const right = clamp(Math.max(rect.x, rect.x + rect.width), 0, slideWidth);
	const bottom = clamp(Math.max(rect.y, rect.y + rect.height), 0, slideHeight);
	return { x: left, y: top, width: right - left, height: bottom - top };
}

/**
 * Example layer drawer: stroke each patch-sized square that meets the viewport.
 * Cells smaller than two CSS pixels are skipped so a zoomed-out slide stays readable.
 */
export function drawVisiblePatchGrid(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	patchSize: number,
	stroke = SELECTION_STROKE
): void {
	if (!(patchSize > 0)) return;
	const bounds = proj.visibleLevel0Bounds;
	const x0 = Math.max(0, Math.floor(bounds.x / patchSize) * patchSize);
	const y0 = Math.max(0, Math.floor(bounds.y / patchSize) * patchSize);
	const x1 = Math.min(proj.slideWidth, bounds.x + bounds.width);
	const y1 = Math.min(proj.slideHeight, bounds.y + bounds.height);
	ctx.save();
	ctx.strokeStyle = stroke;
	ctx.lineWidth = 1;
	let drawn = 0;
	for (let y = y0; y < y1 && drawn < 400; y += patchSize) {
		for (let x = x0; x < x1 && drawn < 400; x += patchSize) {
			const origin = proj.level0ToViewer(x, y);
			const far = proj.level0ToViewer(
				Math.min(x + patchSize, proj.slideWidth),
				Math.min(y + patchSize, proj.slideHeight)
			);
			const width = far.x - origin.x;
			const height = far.y - origin.y;
			if (width < 2 || height < 2) continue;
			ctx.strokeRect(origin.x, origin.y, width, height);
			drawn += 1;
		}
	}
	ctx.restore();
}

export function drawSearchHitLayer(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	hits: readonly ViewerSearchHit[]
): void {
	for (const hit of hits) {
		strokeLevel0Rect(
			ctx,
			proj,
			hit,
			HIT_STROKE,
			hit.label ?? (hit.rank != null ? String(hit.rank) : '')
		);
	}
}

export function drawAnnotationLayer(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	shapes: readonly ViewerAnnotationShape[],
	draft: ViewerAnnotationShape | null
): void {
	for (const shape of shapes) drawAnnotationShape(ctx, proj, shape, false);
	if (draft) drawAnnotationShape(ctx, proj, draft, true);
}

export function drawSelectionLayer(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	selection: SelectionGeometry | null,
	draft: Level0Bounds | null
): void {
	if (selection?.kind === 'patch') {
		strokeLevel0Rect(
			ctx,
			proj,
			{ x: selection.x, y: selection.y, width: selection.size, height: selection.size },
			SELECTION_STROKE,
			'Selected patch'
		);
	} else if (selection?.kind === 'region') {
		strokeLevel0Rect(ctx, proj, selection, SELECTION_STROKE, 'Selected region');
	}
	if (draft && draft.width > 0 && draft.height > 0) {
		strokeLevel0Rect(ctx, proj, draft, '#ffffff', '', true);
	}
}

export function annotationAtPoint(
	shapes: readonly ViewerAnnotationShape[],
	x: number,
	y: number,
	slop: number
): ViewerAnnotationShape | null {
	for (let index = shapes.length - 1; index >= 0; index -= 1) {
		const shape = shapes[index];
		if (shape && shapeContains(shape, x, y, slop)) return shape;
	}
	return null;
}

export function searchHitAtPoint(
	hits: readonly ViewerSearchHit[],
	x: number,
	y: number
): ViewerSearchHit | null {
	for (let index = hits.length - 1; index >= 0; index -= 1) {
		const hit = hits[index];
		if (!hit) continue;
		if (x >= hit.x && y >= hit.y && x <= hit.x + hit.width && y <= hit.y + hit.height) return hit;
	}
	return null;
}

const NICE_MICRONS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];

/** A scale bar whose length is a round number of microns and about `targetPx` CSS pixels. */
export function scaleBarFor(
	mpp: number,
	pixelsPerLevel0: number,
	targetPx = 96
): { px: number; label: string } | null {
	if (!(mpp > 0) || !(pixelsPerLevel0 > 0)) return null;
	const micronsPerPixel = mpp / pixelsPerLevel0;
	let best: number | null = null;
	let bestDistance = Number.POSITIVE_INFINITY;
	for (const step of NICE_MICRONS) {
		const px = step / micronsPerPixel;
		if (px < 40 || px > 180) continue;
		const distance = Math.abs(px - targetPx);
		if (distance < bestDistance) {
			best = step;
			bestDistance = distance;
		}
	}
	if (best == null) {
		const targetMicrons = targetPx * micronsPerPixel;
		best = NICE_MICRONS.reduce((current, step) =>
			Math.abs(step - targetMicrons) < Math.abs(current - targetMicrons) ? step : current
		);
	}
	const px = best / micronsPerPixel;
	const label = best >= 1000 ? `${trimNumber(best / 1000)} mm` : `${trimNumber(best)} μm`;
	return { px, label };
}

export function prepareLayerCanvas(
	canvas: HTMLCanvasElement,
	containerWidth: number,
	containerHeight: number,
	dpr: number
): CanvasRenderingContext2D | null {
	const width = Math.max(1, Math.round(containerWidth * dpr));
	const height = Math.max(1, Math.round(containerHeight * dpr));
	if (canvas.width !== width) canvas.width = width;
	if (canvas.height !== height) canvas.height = height;
	const context = canvas.getContext('2d');
	if (!context) return null;
	context.setTransform(dpr, 0, 0, dpr, 0, 0);
	context.clearRect(0, 0, containerWidth, containerHeight);
	return context;
}

function drawAnnotationShape(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	shape: ViewerAnnotationShape,
	draft: boolean
): void {
	const stroke = shape.isOwn ? NOTE_OWN : NOTE_OTHER;
	if (shape.kind === 'point') {
		const point = proj.level0ToViewer(shape.x, shape.y);
		ctx.save();
		ctx.beginPath();
		ctx.arc(point.x, point.y, shape.selected ? 7 : 5, 0, Math.PI * 2);
		ctx.fillStyle = stroke;
		ctx.strokeStyle = INK;
		ctx.lineWidth = 2;
		if (draft) ctx.setLineDash([4, 3]);
		ctx.fill();
		ctx.stroke();
		if (shape.label) fillLabel(ctx, point.x + 8, point.y - 8, shape.label, stroke);
		ctx.restore();
		return;
	}
	strokeLevel0Rect(
		ctx,
		proj,
		{ x: shape.x, y: shape.y, width: shape.w ?? 0, height: shape.h ?? 0 },
		shape.selected ? SELECTION_STROKE : stroke,
		shape.label,
		draft
	);
}

function strokeLevel0Rect(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	rect: Level0Bounds,
	stroke: string,
	label: string,
	dashed = false
): void {
	const origin = proj.level0ToViewer(rect.x, rect.y);
	const far = proj.level0ToViewer(rect.x + rect.width, rect.y + rect.height);
	const width = far.x - origin.x;
	const height = far.y - origin.y;
	if (width === 0 || height === 0) return;
	ctx.save();
	ctx.lineWidth = 4;
	ctx.strokeStyle = 'rgba(20, 25, 29, 0.8)';
	if (dashed) ctx.setLineDash([6, 4]);
	ctx.strokeRect(origin.x, origin.y, width, height);
	ctx.lineWidth = 2;
	ctx.strokeStyle = stroke;
	ctx.strokeRect(origin.x, origin.y, width, height);
	if (label) fillLabel(ctx, origin.x, origin.y, label, stroke);
	ctx.restore();
}

function fillLabel(
	ctx: CanvasRenderingContext2D,
	x: number,
	y: number,
	label: string,
	color: string
): void {
	ctx.save();
	ctx.font = '600 11px Inter, ui-sans-serif, sans-serif';
	const padX = 6;
	const width = ctx.measureText(label).width + padX * 2;
	const height = 18;
	ctx.fillStyle = color;
	ctx.fillRect(x, y - height, width, height);
	ctx.fillStyle = INK;
	ctx.fillText(label, x + padX, y - 5);
	ctx.restore();
}

function shapeContains(shape: ViewerAnnotationShape, x: number, y: number, slop: number): boolean {
	if (shape.kind === 'point') {
		const dx = x - shape.x;
		const dy = y - shape.y;
		return dx * dx + dy * dy <= slop * slop;
	}
	const width = shape.w ?? 0;
	const height = shape.h ?? 0;
	return (
		x >= shape.x - slop &&
		y >= shape.y - slop &&
		x <= shape.x + width + slop &&
		y <= shape.y + height + slop
	);
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(max, Math.max(min, value));
}

function trimNumber(value: number): string {
	return Number(value.toFixed(2)).toString();
}
