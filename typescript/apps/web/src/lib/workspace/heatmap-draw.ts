import type { Level0Bounds, ViewportProjection } from './overlay-layers.js';
import { fillForScore, type HeatmapPatchScore } from './heatmap-ramp.js';

/**
 * One shaded square per patch, in CSS pixels, aligned to level-0 tissue.
 * Patches outside the viewport are skipped so a few thousand squares stay cheap.
 */
export function drawHeatmapPatches(
	ctx: CanvasRenderingContext2D,
	proj: ViewportProjection,
	patches: readonly HeatmapPatchScore[]
): void {
	const bounds = proj.visibleLevel0Bounds;
	for (const patch of patches) {
		if (!(patch.size > 0) || !patchIntersectsViewport(patch, bounds)) continue;
		const origin = proj.level0ToViewer(patch.x, patch.y);
		const far = proj.level0ToViewer(patch.x + patch.size, patch.y + patch.size);
		const width = far.x - origin.x;
		const height = far.y - origin.y;
		if (!(width > 0) || !(height > 0)) continue;
		ctx.fillStyle = fillForScore(patch.score);
		ctx.fillRect(origin.x, origin.y, width, height);
	}
}

export function patchIntersectsViewport(patch: HeatmapPatchScore, bounds: Level0Bounds): boolean {
	return (
		patch.x < bounds.x + bounds.width &&
		patch.x + patch.size > bounds.x &&
		patch.y < bounds.y + bounds.height &&
		patch.y + patch.size > bounds.y
	);
}
