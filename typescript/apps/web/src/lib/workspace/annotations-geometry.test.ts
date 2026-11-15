import { describe, expect, test } from 'bun:test';
import {
	annotationIsOwn,
	flyTarget,
	formatAnnotationTime,
	kindLabel,
	notePreview,
	regionHandoff,
	roundDrawn,
	roundPoint,
	roundRect,
	sortNewestFirst,
	toViewerShape,
	type AnnotationLike
} from './annotations-geometry';

function mark(overrides: Partial<AnnotationLike> = {}): AnnotationLike {
	return {
		id: 'a',
		slide_id: 'slide-a',
		kind: 'rect',
		label: 'Margin',
		note: 'Starts at the inked edge and continues.',
		created_at: '2026-11-03T11:00:00Z',
		can_edit: true,
		author: { id: 'path-okafor', name: 'Dr A. Okafor', is_synthetic: true },
		geometry: { x: 128, y: 64, width: 512, height: 256 },
		...overrides
	};
}

describe('level-0 rounding', () => {
	test('rounds each rectangle edge with Math.round', () => {
		expect(roundRect({ x: 10.4, y: 20.6, w: 30.5, h: 40.2 })).toEqual({
			ok: true,
			kind: 'rect',
			geometry: {
				x: Math.round(10.4),
				y: Math.round(20.6),
				width: Math.round(30.5),
				height: Math.round(40.2)
			}
		});
		expect(roundDrawn({ kind: 'rect', x: 1.2, y: 3.8, w: 4.1, h: 5.9 }, null)).toEqual({
			ok: true,
			kind: 'rect',
			geometry: { x: 1, y: 4, width: 4, height: 6 }
		});
	});

	test('rounds a point with Math.round and keeps it on the slide', () => {
		expect(roundPoint({ x: 8.4, y: 9.6 })).toEqual({
			ok: true,
			kind: 'point',
			geometry: { x: Math.round(8.4), y: Math.round(9.6) }
		});
		expect(roundPoint({ x: 99.6, y: -0.4 }, { width: 100, height: 80 })).toEqual({
			ok: true,
			kind: 'point',
			geometry: { x: 99, y: 0 }
		});
	});

	test('rejects a rectangle that rounds to an empty mark', () => {
		expect(roundRect({ x: 4, y: 5, w: 0.4, h: 12 }).ok).toBe(false);
	});

	test('clamps a rectangle so the far edge stays inside the slide', () => {
		expect(roundRect({ x: 90.2, y: 10, w: 40.4, h: 20 }, { width: 100, height: 80 })).toEqual({
			ok: true,
			kind: 'rect',
			geometry: { x: 90, y: 10, width: 10, height: 20 }
		});
	});
});

describe('annotation ownership and list shape', () => {
	test('recomputes ownership from the acting pathologist, not a stale can_edit flag', () => {
		const mine = mark();
		expect(annotationIsOwn(mine, 'path-okafor')).toBe(true);
		expect(annotationIsOwn(mine, 'path-mensah')).toBe(false);
		expect(annotationIsOwn({ ...mine, can_edit: false }, 'path-okafor')).toBe(true);
		expect(annotationIsOwn(mine, null)).toBe(true);
		expect(annotationIsOwn({ ...mine, can_edit: false }, null)).toBe(false);
	});

	test('lists newest first and maps rectangles and points onto the viewer', () => {
		const older = mark({ id: 'older', created_at: '2026-11-01T00:00:00Z' });
		const newer = mark({
			id: 'newer',
			created_at: '2026-11-04T00:00:00Z',
			kind: 'point',
			geometry: { x: 4, y: 5 }
		});
		expect(sortNewestFirst([older, newer]).map((item) => item.id)).toEqual(['newer', 'older']);
		expect(toViewerShape(older, 'path-okafor', 'older')).toEqual({
			id: 'older',
			kind: 'rect',
			x: 128,
			y: 64,
			w: 512,
			h: 256,
			label: 'Margin',
			isOwn: true,
			selected: true
		});
		expect(toViewerShape(newer, 'path-mensah', null)).toEqual({
			id: 'newer',
			kind: 'point',
			x: 4,
			y: 5,
			label: 'Margin',
			isOwn: false,
			selected: false
		});
	});

	test('previews the start of a note and names the kind', () => {
		expect(notePreview('  line one\nline two  ')).toBe('line one line two');
		expect(notePreview('x'.repeat(90))?.endsWith('…')).toBe(true);
		expect(notePreview('   ')).toBeNull();
		expect(kindLabel('rect')).toBe('Rectangle');
		expect(kindLabel('point')).toBe('Point');
		expect(formatAnnotationTime('2026-11-03T11:00:00Z')).toContain('2026');
		expect(formatAnnotationTime('not-a-date')).toBe('not-a-date');
	});

	test('hands a rectangle to search and frames a point for go-to', () => {
		const rectangle = mark();
		expect(regionHandoff(rectangle)).toEqual({
			slideId: 'slide-a',
			x: 128,
			y: 64,
			width: 512,
			height: 256
		});
		expect(flyTarget(rectangle)).toEqual(regionHandoff(rectangle));
		const point = mark({ kind: 'point', geometry: { x: 1000, y: 700 } });
		expect(regionHandoff(point)).toBeNull();
		expect(flyTarget(point)).toEqual({
			slideId: 'slide-a',
			x: 1000 - 256,
			y: 700 - 256,
			width: 512,
			height: 512
		});
	});
});
