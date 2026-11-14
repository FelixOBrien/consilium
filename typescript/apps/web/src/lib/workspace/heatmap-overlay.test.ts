import { afterEach, describe, expect, test } from 'bun:test';
import { projectionFromVisibleBounds } from './overlay-layers.js';
import { patchIntersectsViewport, drawHeatmapPatches } from './heatmap-draw.js';
import { installReportWordHook, readHeatmapDevHook } from './heatmap-dev.js';
import { heatmapTextBody, loadSlideHeatmap } from './heatmap-load.js';
import {
	fillForScore,
	normalisePatches,
	normaliseScores,
	scoreLightness,
	scoreToRgba,
	scoreYellowBlue,
	SIMILARITY_LABEL,
	type HeatmapPatchScore
} from './heatmap-ramp.js';
import {
	EMPTY_HEATMAP_VIEW,
	reduceHeatmap,
	syncHeatmapTarget,
	type HeatmapView
} from './heatmap-session.js';

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
	delete (globalThis as { __consiliumSelectReportWord?: unknown }).__consiliumSelectReportWord; // pragma: allowlist secret
});

describe('score normalisation and the colour-vision ramp', () => {
	test('min-max normalises a slide and is idempotent once scores span 0 to 1', () => {
		expect(normaliseScores([])).toEqual([]);
		expect(normaliseScores([0.4, 0.4, 0.4])).toEqual([0, 0, 0]);
		expect(normaliseScores([2, 4, 6])).toEqual([0, 0.5, 1]);
		expect(normaliseScores([-2, 0, 2])).toEqual([0, 0.5, 1]);
		expect(normaliseScores([Number.NaN, 3])).toEqual([0, 0]);
		const spanned = normaliseScores([0.2, 0.6, 1]);
		expect(normaliseScores(spanned)).toEqual(spanned);
		const patches: HeatmapPatchScore[] = [
			{ x: 0, y: 10, size: 512, score: 1 },
			{ x: 512, y: 10, size: 512, score: 3 }
		];
		expect(normalisePatches(patches)).toEqual([
			{ x: 0, y: 10, size: 512, score: 0 },
			{ x: 512, y: 10, size: 512, score: 1 }
		]);
	});

	test('the fixed ramp runs teal to amber, lightens, and stays distinct under common CVD', () => {
		const low = scoreToRgba(0);
		const high = scoreToRgba(1);
		expect(low).toEqual({ r: 0, g: 122, b: 140, a: 0.3 });
		expect(high).toEqual({ r: 255, g: 188, b: 48, a: 0.84 });
		expect(low.b).toBeGreaterThan(low.r);
		expect(high.r).toBeGreaterThan(high.b);
		expect(high.a).toBeGreaterThan(low.a);
		expect(scoreLightness(1)).toBeGreaterThan(scoreLightness(0) + 0.2);
		expect(scoreYellowBlue(1)).toBeGreaterThan(scoreYellowBlue(0));

		let previousL = scoreLightness(0);
		let previousB = scoreYellowBlue(0);
		for (const score of [0.25, 0.5, 0.75, 1]) {
			const lightness = scoreLightness(score);
			const yellow = scoreYellowBlue(score);
			expect(lightness >= previousL).toBe(true);
			expect(yellow >= previousB).toBe(true);
			const color = scoreToRgba(score);
			expect(color.r >= 0 && color.r <= 255).toBe(true);
			expect(color.g >= 0 && color.g <= 255).toBe(true);
			expect(color.b >= 0 && color.b <= 255).toBe(true);
			previousL = lightness;
			previousB = yellow;
		}

		expect(fillForScore(0)).toBe('rgba(0, 122, 140, 0.3)');
		expect(fillForScore(1)).toBe('rgba(255, 188, 48, 0.84)');
		expect(fillForScore(Number.NaN)).toBe(fillForScore(0));

		const pink = { r: 224, g: 170, b: 184 };
		const purple = { r: 96, g: 62, b: 138 };
		expect(distance(blend(0, pink), blend(1, pink))).toBeGreaterThan(80);
		expect(distance(blend(0, purple), blend(1, purple))).toBeGreaterThan(80);
		expect(cvdDistance('protanopia')).toBeGreaterThan(40);
		expect(cvdDistance('deuteranopia')).toBeGreaterThan(40);
		expect(SIMILARITY_LABEL).toBe('Embedding similarity — not a finding');
	});
});

describe('viewport culling and level-0 alignment', () => {
	test('draws each visible patch from its level-0 corners and skips the rest', () => {
		const fitted = projectionFromVisibleBounds({
			slideWidth: 4000,
			slideHeight: 3000,
			containerWidth: 800,
			containerHeight: 600,
			dpr: 2,
			visible: { x: 1000, y: 500, width: 2000, height: 1500 }
		});
		const patch: HeatmapPatchScore = { x: 1500, y: 800, size: 500, score: 1 };
		const rects: number[][] = [];
		const styles: string[] = [];
		drawHeatmapPatches(mockContext(rects, styles), fitted, [
			patch,
			{ x: 0, y: 0, size: 500, score: 0.2 },
			{ x: 3600, y: 2400, size: 200, score: 0.4 },
			{ x: 900, y: 400, size: 200, score: 0 }
		]);
		expect(rects).toHaveLength(2);
		const origin = fitted.level0ToViewer(patch.x, patch.y);
		const far = fitted.level0ToViewer(patch.x + patch.size, patch.y + patch.size);
		expect(rects[0]).toEqual([origin.x, origin.y, far.x - origin.x, far.y - origin.y]);
		expect(fitted.viewerToLevel0(rects[0]![0]!, rects[0]![1]!).x).toBeCloseTo(patch.x, 6);
		expect(fitted.viewerToLevel0(rects[0]![0]!, rects[0]![1]!).y).toBeCloseTo(patch.y, 6);
		const farBack = fitted.viewerToLevel0(
			rects[0]![0]! + rects[0]![2]!,
			rects[0]![1]! + rects[0]![3]!
		);
		expect(farBack.x).toBeCloseTo(patch.x + patch.size, 6);
		expect(farBack.y).toBeCloseTo(patch.y + patch.size, 6);
		expect(styles[0]).toBe(fillForScore(1));

		const zoomed = projectionFromVisibleBounds({
			slideWidth: 4000,
			slideHeight: 3000,
			containerWidth: 800,
			containerHeight: 600,
			dpr: 1,
			visible: { x: 1400, y: 700, width: 800, height: 600 }
		});
		const zoomedRects: number[][] = [];
		drawHeatmapPatches(mockContext(zoomedRects, []), zoomed, [patch]);
		const zoomedOrigin = zoomed.level0ToViewer(patch.x, patch.y);
		const zoomedFar = zoomed.level0ToViewer(patch.x + patch.size, patch.y + patch.size);
		expect(zoomedRects[0]).toEqual([
			zoomedOrigin.x,
			zoomedOrigin.y,
			zoomedFar.x - zoomedOrigin.x,
			zoomedFar.y - zoomedOrigin.y
		]);
		expect(Math.abs((zoomedRects[0]?.[2] ?? 0) - (rects[0]?.[2] ?? 0)) > 1).toBe(true);
		expect(zoomed.pixelsPerLevel0).toBeGreaterThan(fitted.pixelsPerLevel0);
	});

	test('culls a 5,000 patch grid down to the squares inside the viewport', () => {
		const patches: HeatmapPatchScore[] = [];
		for (let index = 0; index < 5000; index += 1) {
			patches.push({
				x: (index % 100) * 10,
				y: Math.floor(index / 100) * 10,
				size: 10,
				score: (index % 10) / 9
			});
		}
		const bounds = { x: 0, y: 0, width: 100, height: 100 };
		const visible = patches.filter((patch) => patchIntersectsViewport(patch, bounds));
		expect(visible).toHaveLength(100);
		const projection = projectionFromVisibleBounds({
			slideWidth: 1000,
			slideHeight: 500,
			containerWidth: 200,
			containerHeight: 200,
			dpr: 1,
			visible: bounds
		});
		const rects: number[][] = [];
		const started = performance.now();
		drawHeatmapPatches(mockContext(rects, []), projection, patches);
		expect(performance.now() - started < 200).toBe(true);
		expect(rects).toHaveLength(100);
		expect(rects[0]).toEqual([0, 0, 20, 20]);
		expect(rects.some((rect) => rect[0]! >= 200 || rect[1]! >= 200)).toBe(false);
	});
});

describe('one overlay at a time', () => {
	test('a stale response cannot replace the word that is still loading', () => {
		let view = paint('s1', 'stroma', 1, [{ x: 0, y: 0, size: 512, score: 1 }]);
		view = syncHeatmapTarget(view, { slideId: 's1', phrase: 'carcinoma', seq: 2 });
		expect(view.phrase).toBe('carcinoma');
		expect(view.loading).toBe(true);
		expect(view.overlay?.phrase).toBe('stroma');

		const stale = reduceHeatmap(view, {
			type: 'success',
			slideId: 's1',
			seq: 1,
			phrase: 'stroma',
			patches: [{ x: 512, y: 0, size: 512, score: 0.2 }]
		});
		expect(stale.overlay?.phrase).toBe('stroma');
		expect(stale.phrase).toBe('carcinoma');
		expect(stale.loading).toBe(true);

		const failed = reduceHeatmap(view, {
			type: 'failure',
			slideId: 's1',
			seq: 1,
			message: 'Similarity could not be computed.'
		});
		expect(failed.error).toBeNull();
		expect(failed.overlay?.phrase).toBe('stroma');

		view = reduceHeatmap(view, {
			type: 'success',
			slideId: 's1',
			seq: 2,
			phrase: 'carcinoma',
			patches: [{ x: 1024, y: 0, size: 512, score: 1 }]
		});
		expect(view.loading).toBe(false);
		expect(view.overlay?.phrase).toBe('carcinoma');
		expect(view.overlay?.patches[0]?.x).toBe(1024);

		const late = reduceHeatmap(view, {
			type: 'success',
			slideId: 's1',
			seq: 1,
			phrase: 'stroma',
			patches: [{ x: 0, y: 0, size: 512, score: 1 }]
		});
		expect(late).toBe(view);
	});

	test('a failure keeps the current shading and names the problem beside the word', () => {
		const loading = syncHeatmapTarget(EMPTY_HEATMAP_VIEW, {
			slideId: 's1',
			phrase: 'stroma',
			seq: 4
		});
		const failed = reduceHeatmap(loading, {
			type: 'failure',
			slideId: 's1',
			seq: 4,
			message: 'Text encoder is not configured.'
		});
		expect(failed.phrase).toBe('stroma');
		expect(failed.loading).toBe(false);
		expect(failed.error).toBe('Text encoder is not configured.');
		expect(failed.overlay).toBeNull();
	});

	test('clearing or changing slide removes the shading before any in-flight response returns', () => {
		const painted = paint('s1', 'stroma', 1, [{ x: 0, y: 0, size: 512, score: 0.8 }]);
		const cleared = syncHeatmapTarget(painted, { slideId: 's1', phrase: null, seq: null });
		expect(cleared).toEqual(EMPTY_HEATMAP_VIEW);
		expect(
			reduceHeatmap(cleared, {
				type: 'success',
				slideId: 's1',
				seq: 1,
				phrase: 'stroma',
				patches: [{ x: 0, y: 0, size: 512, score: 0.8 }]
			})
		).toBe(cleared);

		const switched = syncHeatmapTarget(painted, { slideId: 's2', phrase: null, seq: null });
		expect(switched.overlay).toBeNull();
		expect(switched.phrase).toBeNull();

		const nextSlide = syncHeatmapTarget(painted, { slideId: 's2', phrase: 'stroma', seq: 3 });
		expect(nextSlide.overlay).toBeNull();
		expect(nextSlide.slideId).toBe('s2');
		expect(nextSlide.loading).toBe(true);
		const wrongSlide = reduceHeatmap(nextSlide, {
			type: 'success',
			slideId: 's1',
			seq: 1,
			phrase: 'stroma',
			patches: painted.overlay?.patches ?? []
		});
		expect(wrongSlide.overlay).toBeNull();
	});

	test('the same request does not restart over a response that already arrived', () => {
		const painted = paint('s1', 'stroma', 1, [{ x: 0, y: 0, size: 512, score: 1 }]);
		expect(syncHeatmapTarget(painted, { slideId: 's1', phrase: 'stroma', seq: 1 })).toBe(painted);
		expect(syncHeatmapTarget(painted, { slideId: 's1', phrase: '  ', seq: 1 })).toEqual(
			EMPTY_HEATMAP_VIEW
		);
	});
});

describe('heatmap request and dev hooks', () => {
	test('sends the report word as text alone', async () => {
		expect(heatmapTextBody('stroma')).toEqual({ text: 'stroma' });
		let body = '';
		let url = '';
		let method = '';
		globalThis.fetch = (async (input: RequestInfo | URL) => {
			const request = input instanceof Request ? input : new Request(input);
			method = request.method;
			url = request.url;
			body = await request.text();
			return Response.json({
				text: 'stroma',
				concept_id: null,
				negative_text: null,
				notice: SIMILARITY_LABEL,
				truncated: false,
				patches: [
					{ x: 0, y: 0, size: 512, score: 0.25 },
					{ x: 512, y: 0, size: 512, score: 0.75 }
				],
				top: []
			});
		}) as typeof fetch;

		const loaded = await loadSlideHeatmap('FX-B042A-s1', 'stroma');
		expect(method).toBe('POST');
		expect(url).toContain('/api/slides/FX-B042A-s1/heatmap');
		expect(JSON.parse(body)).toEqual({ text: 'stroma' });
		expect(Object.keys(JSON.parse(body))).toEqual(['text']);
		expect(loaded.kind).toBe('ok');
		if (loaded.kind === 'ok') {
			expect(loaded.patches).toEqual([
				{ x: 0, y: 0, size: 512, score: 0 },
				{ x: 512, y: 0, size: 512, score: 1 }
			]);
		}
	});

	test('an aborted call and an error payload do not invent a diagnosis', async () => {
		const controller = new AbortController();
		controller.abort();
		expect((await loadSlideHeatmap('s1', 'stroma', controller.signal)).kind).toBe('aborted');

		globalThis.fetch = (async () =>
			Response.json(
				{ error: { code: 'error', message: 'Text encoder is not configured.' } },
				{ status: 500 }
			)) as typeof fetch;
		const failed = await loadSlideHeatmap('s1', 'stroma');
		expect(failed).toEqual({ kind: 'error', message: 'Text encoder is not configured.' });
	});

	test('reads the url hook and installs the window hook without a phrase field', () => {
		expect(readHeatmapDevHook('?word=stroma&panel=report')).toEqual({
			word: 'stroma',
			debugOverlay: false
		});
		expect(readHeatmapDevHook('debug_overlay=1&word=%20')).toEqual({
			word: null,
			debugOverlay: true
		});
		const seen: Array<string | null> = [];
		const remove = installReportWordHook((phrase) => {
			seen.push(phrase);
		});
		const host = globalThis as typeof globalThis & {
			__consiliumSelectReportWord?: (phrase: string | null) => void; // pragma: allowlist secret
		};
		host.__consiliumSelectReportWord?.(' carcinoma '); // pragma: allowlist secret
		host.__consiliumSelectReportWord?.(null); // pragma: allowlist secret
		host.__consiliumSelectReportWord?.('   '); // pragma: allowlist secret
		remove();
		expect(seen).toEqual(['carcinoma', null, null]);
		expect(host.__consiliumSelectReportWord).toBe(undefined); // pragma: allowlist secret
	});
});

function paint(
	slideId: string,
	phrase: string,
	seq: number,
	patches: HeatmapPatchScore[]
): HeatmapView {
	const loading = syncHeatmapTarget(EMPTY_HEATMAP_VIEW, { slideId, phrase, seq });
	return reduceHeatmap(loading, { type: 'success', slideId, seq, phrase, patches });
}

function mockContext(rects: number[][], styles: string[]): CanvasRenderingContext2D {
	const context = {
		fillStyle: '',
		fillRect(x: number, y: number, width: number, height: number) {
			styles.push(context.fillStyle);
			rects.push([x, y, width, height]);
		}
	};
	return context as unknown as CanvasRenderingContext2D;
}

function blend(
	score: number,
	tissue: { r: number; g: number; b: number }
): { r: number; g: number; b: number } {
	const ink = scoreToRgba(score);
	return {
		r: ink.r * ink.a + tissue.r * (1 - ink.a),
		g: ink.g * ink.a + tissue.g * (1 - ink.a),
		b: ink.b * ink.a + tissue.b * (1 - ink.a)
	};
}

function distance(
	left: { r: number; g: number; b: number },
	right: { r: number; g: number; b: number }
): number {
	return Math.hypot(left.r - right.r, left.g - right.g, left.b - right.b);
}

function cvdDistance(kind: 'protanopia' | 'deuteranopia'): number {
	return distance(simulate(scoreToRgba(0), kind), simulate(scoreToRgba(1), kind));
}

function simulate(
	color: { r: number; g: number; b: number },
	kind: 'protanopia' | 'deuteranopia'
): { r: number; g: number; b: number } {
	const linear = [color.r, color.g, color.b].map((channel) => {
		const value = channel / 255;
		return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
	});
	const matrix =
		kind === 'protanopia'
			? [
					[0.152286, 1.052583, -0.204868],
					[0.114503, 0.786281, 0.099216],
					[-0.003882, -0.048116, 1.051998]
				]
			: [
					[0.367322, 0.860646, -0.227968],
					[0.280085, 0.672501, 0.047413],
					[-0.01182, 0.04294, 0.968881]
				];
	const mixed = matrix.map(
		(row) => row[0]! * linear[0]! + row[1]! * linear[1]! + row[2]! * linear[2]!
	);
	return {
		r: srgb(mixed[0]!),
		g: srgb(mixed[1]!),
		b: srgb(mixed[2]!)
	};
}

function srgb(channel: number): number {
	const value = channel <= 0.0031308 ? 12.92 * channel : 1.055 * channel ** (1 / 2.4) - 0.055;
	return Math.round(Math.min(1, Math.max(0, value)) * 255);
}
