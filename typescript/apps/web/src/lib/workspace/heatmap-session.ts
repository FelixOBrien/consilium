import type { HeatmapPatchScore } from './heatmap-ramp.js';

/**
 * One overlay at a time.
 * A new word keeps the previous squares until its own response arrives.
 * A null request or a slide change drops the shading immediately.
 * Responses whose sequence or slide no longer matches are ignored.
 */
export type HeatmapOverlay = {
	slideId: string;
	phrase: string;
	seq: number;
	patches: readonly HeatmapPatchScore[];
};

export type HeatmapView = {
	phrase: string | null;
	slideId: string | null;
	seq: number | null;
	loading: boolean;
	error: string | null;
	overlay: HeatmapOverlay | null;
};

export type HeatmapTarget = {
	slideId: string | null;
	phrase: string | null;
	seq: number | null;
};

export type HeatmapResult =
	| {
			type: 'success';
			slideId: string;
			seq: number;
			phrase: string;
			patches: readonly HeatmapPatchScore[];
	  }
	| {
			type: 'failure';
			slideId: string;
			seq: number;
			message: string;
	  };

export const EMPTY_HEATMAP_VIEW: HeatmapView = {
	phrase: null,
	slideId: null,
	seq: null,
	loading: false,
	error: null,
	overlay: null
};

export function syncHeatmapTarget(view: HeatmapView, target: HeatmapTarget): HeatmapView {
	const phrase = target.phrase?.trim() ?? '';
	if (target.slideId == null || phrase === '' || target.seq == null) {
		return isIdle(view) ? view : EMPTY_HEATMAP_VIEW;
	}
	if (view.slideId != null && view.slideId !== target.slideId) {
		return {
			phrase,
			slideId: target.slideId,
			seq: target.seq,
			loading: true,
			error: null,
			overlay: null
		};
	}
	if (view.seq === target.seq && view.slideId === target.slideId && view.phrase === phrase) {
		return view;
	}
	return {
		phrase,
		slideId: target.slideId,
		seq: target.seq,
		loading: true,
		error: null,
		overlay: view.overlay?.slideId === target.slideId ? view.overlay : null
	};
}

export function reduceHeatmap(view: HeatmapView, result: HeatmapResult): HeatmapView {
	if (view.slideId !== result.slideId || view.seq !== result.seq || view.phrase == null)
		return view;
	if (result.type === 'failure') {
		return { ...view, loading: false, error: result.message };
	}
	return {
		...view,
		loading: false,
		error: null,
		overlay: {
			slideId: result.slideId,
			phrase: view.phrase,
			seq: result.seq,
			patches: result.patches
		}
	};
}

function isIdle(view: HeatmapView): boolean {
	return (
		view.phrase == null &&
		view.slideId == null &&
		view.seq == null &&
		!view.loading &&
		view.error == null &&
		view.overlay == null
	);
}
