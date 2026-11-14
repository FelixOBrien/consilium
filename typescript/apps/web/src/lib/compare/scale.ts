/**
 * Physical scale for linked compare panes.
 *
 * OpenSeadragon image zoom is screen pixels per level-0 pixel: 1 is native
 * resolution and 0.5 is half size (Viewport.viewportToImageZoom). Microns per
 * screen pixel are therefore `mpp / imageZoom`.
 */

export type PaneView = {
	x: number;
	y: number;
	zoom: number;
};

export function hasMpp(mpp: number | null | undefined): mpp is number {
	return typeof mpp === 'number' && Number.isFinite(mpp) && mpp > 0;
}

/** Both slides can be locked to the same microns per screen pixel. */
export function physicalScaleAvailable(
	leftMpp: number | null | undefined,
	rightMpp: number | null | undefined
): boolean {
	return hasMpp(leftMpp) && hasMpp(rightMpp);
}

export function micronsPerScreenPixel(mpp: number, imageZoom: number): number {
	return mpp / imageZoom;
}

/**
 * Image zoom on the target slide that matches the source's microns per screen
 * pixel. Without `mpp` on either slide, zoom is matched relatively.
 */
export function matchedZoom(
	sourceZoom: number,
	sourceMpp: number | null | undefined,
	targetMpp: number | null | undefined
): number {
	if (!(sourceZoom > 0) || !hasMpp(sourceMpp) || !hasMpp(targetMpp)) return sourceZoom;
	return (sourceZoom * targetMpp) / sourceMpp;
}

/** Level-0 pixel delta on the target for a level-0 delta on the source. */
export function panDelta(
	dx: number,
	dy: number,
	sourceMpp: number | null | undefined,
	targetMpp: number | null | undefined
): { x: number; y: number } {
	if (!hasMpp(sourceMpp) || !hasMpp(targetMpp)) return { x: dx, y: dy };
	const scale = sourceMpp / targetMpp;
	return { x: dx * scale, y: dy * scale };
}

/** Move the target by the source's physical pan and match physical scale. */
export function linkedView(input: {
	sourcePrev: PaneView;
	sourceNext: PaneView;
	targetPrev: PaneView;
	sourceMpp: number | null | undefined;
	targetMpp: number | null | undefined;
}): PaneView {
	const delta = panDelta(
		input.sourceNext.x - input.sourcePrev.x,
		input.sourceNext.y - input.sourcePrev.y,
		input.sourceMpp,
		input.targetMpp
	);
	return {
		x: input.targetPrev.x + delta.x,
		y: input.targetPrev.y + delta.y,
		zoom: matchedZoom(input.sourceNext.zoom, input.sourceMpp, input.targetMpp)
	};
}

/**
 * Turn linking back on without jumping the tissue under each centre.
 * The target keeps its centre and adopts the source's physical scale.
 */
export function relinkAlignment(
	source: PaneView,
	target: PaneView,
	sourceMpp: number | null | undefined,
	targetMpp: number | null | undefined
): PaneView {
	return {
		x: target.x,
		y: target.y,
		zoom: matchedZoom(source.zoom, sourceMpp, targetMpp)
	};
}
