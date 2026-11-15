import { describe, expect, test } from 'bun:test';
import {
	LAYER_ORDER,
	annotationAtPoint,
	clampLevel0Rect,
	drawVisiblePatchGrid,
	projectionFromVisibleBounds,
	scaleBarFor,
	searchHitAtPoint,
	visibleBoundsAround
} from './overlay-layers';

describe('viewport projection', () => {
	const projection = projectionFromVisibleBounds({
		slideWidth: 10000,
		slideHeight: 8000,
		containerWidth: 500,
		containerHeight: 400,
		dpr: 2,
		visible: { x: 1000, y: 2000, width: 2500, height: 2000 }
	});

	test('maps level-0 pixels onto the viewer and back', () => {
		for (const [x, y] of [
			[1000, 2000],
			[1500, 2500],
			[3500, 4000],
			[0, 0],
			[9000, 7000]
		] as const) {
			const viewer = projection.level0ToViewer(x, y);
			const level0 = projection.viewerToLevel0(viewer.x, viewer.y);
			expect(level0.x).toBeCloseTo(x, 6);
			expect(level0.y).toBeCloseTo(y, 6);
		}
	});

	test('puts the visible origin at the viewer origin and the far corner at the container edge', () => {
		expect(projection.level0ToViewer(1000, 2000)).toEqual({ x: 0, y: 0 });
		const far = projection.level0ToViewer(3500, 4000);
		expect(far.x).toBeCloseTo(500, 6);
		expect(far.y).toBeCloseTo(400, 6);
	});

	test('reports CSS pixels per level-0 pixel and ignores devicePixelRatio', () => {
		expect(projection.pixelsPerLevel0).toBeCloseTo(500 / 2500, 6);
		expect(projection.dpr).toBe(2);
		const css = projectionFromVisibleBounds({
			slideWidth: 10000,
			slideHeight: 8000,
			containerWidth: 500,
			containerHeight: 400,
			dpr: 1,
			visible: { x: 1000, y: 2000, width: 2500, height: 2000 }
		});
		expect(css.level0ToViewer(1500, 2500)).toEqual(projection.level0ToViewer(1500, 2500));
	});

	test('a zoomed centre round-trips through the visible bounds', () => {
		const center = { x: 4200, y: 2600 };
		const visible = visibleBoundsAround(center, 0.25, 800, 600);
		const framed = projectionFromVisibleBounds({
			slideWidth: 20000,
			slideHeight: 16000,
			containerWidth: 800,
			containerHeight: 600,
			dpr: 1,
			visible
		});
		expect(framed.pixelsPerLevel0).toBeCloseTo(0.25, 6);
		const viewer = framed.level0ToViewer(center.x, center.y);
		expect(viewer.x).toBeCloseTo(400, 6);
		expect(viewer.y).toBeCloseTo(300, 6);
		const back = framed.viewerToLevel0(viewer.x, viewer.y);
		expect(back.x).toBeCloseTo(center.x, 6);
		expect(back.y).toBeCloseTo(center.y, 6);
	});
});

describe('level-0 geometry helpers', () => {
	test('clamps a dragged rectangle to the slide and normalises a negative drag', () => {
		expect(clampLevel0Rect({ x: -40, y: 20, width: 100, height: 80 }, 1000, 800)).toEqual({
			x: 0,
			y: 20,
			width: 60,
			height: 80
		});
		expect(clampLevel0Rect({ x: 500, y: 400, width: -120, height: -50 }, 1000, 800)).toEqual({
			x: 380,
			y: 350,
			width: 120,
			height: 50
		});
	});

	test('layer order is heatmap, search hits, annotations, then selection', () => {
		expect(LAYER_ORDER).toEqual(['heatmap', 'searchHits', 'annotations', 'selection']);
	});

	test('the example patch-grid drawer outlines each visible cell', () => {
		const projection = projectionFromVisibleBounds({
			slideWidth: 4096,
			slideHeight: 4096,
			containerWidth: 512,
			containerHeight: 512,
			dpr: 1,
			visible: { x: 0, y: 0, width: 1024, height: 1024 }
		});
		const rects: number[][] = [];
		const context = {
			strokeStyle: '',
			lineWidth: 0,
			save() {},
			restore() {},
			strokeRect(x: number, y: number, width: number, height: number) {
				rects.push([x, y, width, height]);
			}
		} as unknown as CanvasRenderingContext2D;
		drawVisiblePatchGrid(context, projection, 512);
		expect(rects).toHaveLength(4);
		expect(rects[0]).toEqual([0, 0, 256, 256]);
	});

	test('hit testing prefers the topmost annotation and search hit', () => {
		const note = annotationAtPoint(
			[
				{ id: 'a', kind: 'rect', x: 0, y: 0, w: 100, h: 100, label: 'A', isOwn: true },
				{ id: 'b', kind: 'rect', x: 50, y: 50, w: 100, h: 100, label: 'B', isOwn: false }
			],
			60,
			60,
			0
		);
		expect(note?.id).toBe('b');
		const hit = searchHitAtPoint(
			[
				{ id: '1', x: 0, y: 0, width: 40, height: 40 },
				{ id: '2', x: 10, y: 10, width: 40, height: 40, rank: 2 }
			],
			20,
			20
		);
		expect(hit?.id).toBe('2');
		expect(
			annotationAtPoint(
				[{ id: 'p', kind: 'point', x: 10, y: 10, label: 'P', isOwn: true }],
				12,
				11,
				4
			)?.id
		).toBe('p');
	});

	test('builds a round micron scale bar from mpp', () => {
		const bar = scaleBarFor(0.5, 1, 96);
		expect(bar).toEqual({ px: 100, label: '50 μm' });
		expect(scaleBarFor(0, 1)).toBeNull();
	});
});
