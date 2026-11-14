import { describe, expect, test } from 'bun:test';
import { LinkSession } from './link.js';
import {
	hasMpp,
	linkedView,
	matchedZoom,
	micronsPerScreenPixel,
	panDelta,
	physicalScaleAvailable,
	relinkAlignment,
	type PaneView
} from './scale.js';

const leftAt = (zoom: number, x = 1000, y = 500): PaneView => ({ x, y, zoom });

describe('physical scale', () => {
	test('equal mpp keeps zoom and pans in level-0 pixels', () => {
		expect(matchedZoom(1.5, 0.5, 0.5)).toBeCloseTo(1.5);
		expect(panDelta(40, -10, 0.5, 0.5)).toEqual({ x: 40, y: -10 });
		const next = linkedView({
			sourcePrev: leftAt(1),
			sourceNext: leftAt(2, 1100, 480),
			targetPrev: { x: 300, y: 80, zoom: 1 },
			sourceMpp: 0.5,
			targetMpp: 0.5
		});
		expect(next).toEqual({ x: 400, y: 60, zoom: 2 });
	});

	test('different mpp matches microns per screen pixel and physical pan', () => {
		const sourceMpp = 0.5;
		const targetMpp = 0.25;
		const zoom = matchedZoom(1, sourceMpp, targetMpp);
		expect(zoom).toBeCloseTo(0.5);
		expect(micronsPerScreenPixel(sourceMpp, 1)).toBeCloseTo(micronsPerScreenPixel(targetMpp, zoom));
		expect(panDelta(100, 40, sourceMpp, targetMpp)).toEqual({ x: 200, y: 80 });
	});

	test('linked pan keeps the micron offset between centres', () => {
		const sourceMpp = 0.5;
		const targetMpp = 0.25;
		const sourcePrev = leftAt(1, 1000, 500);
		const targetPrev = { x: 3000, y: 1000, zoom: 0.5 };
		const offsetX = sourcePrev.x * sourceMpp - targetPrev.x * targetMpp;
		const offsetY = sourcePrev.y * sourceMpp - targetPrev.y * targetMpp;
		const sourceNext = leftAt(2, 1100, 480);
		const next = linkedView({
			sourcePrev,
			sourceNext,
			targetPrev,
			sourceMpp,
			targetMpp
		});
		expect(sourceNext.x * sourceMpp - next.x * targetMpp).toBeCloseTo(offsetX);
		expect(sourceNext.y * sourceMpp - next.y * targetMpp).toBeCloseTo(offsetY);
		expect(micronsPerScreenPixel(targetMpp, next.zoom)).toBeCloseTo(
			micronsPerScreenPixel(sourceMpp, sourceNext.zoom)
		);
	});

	test('missing mpp falls back to relative zoom and level-0 pan', () => {
		expect(hasMpp(null)).toBe(false);
		expect(hasMpp(0)).toBe(false);
		expect(hasMpp(Number.NaN)).toBe(false);
		expect(physicalScaleAvailable(0.5, null)).toBe(false);
		expect(physicalScaleAvailable(0.5, 0.25)).toBe(true);
		expect(matchedZoom(2, null, 0.5)).toBe(2);
		expect(matchedZoom(2, 0.5, undefined)).toBe(2);
		expect(panDelta(10, -4, 0.5, null)).toEqual({ x: 10, y: -4 });
		const linked = linkedView({
			sourcePrev: { x: 0, y: 0, zoom: 1 },
			sourceNext: { x: 8, y: -2, zoom: 2 },
			targetPrev: { x: 100, y: 50, zoom: 1 },
			sourceMpp: 0.25,
			targetMpp: null
		});
		expect(linked).toEqual({ x: 108, y: 48, zoom: 2 });
	});

	test('relink keeps the target centre and adopts the source scale', () => {
		const aligned = relinkAlignment(
			{ x: 10, y: 10, zoom: 1 },
			{ x: 400, y: 80, zoom: 4 },
			0.5,
			0.25
		);
		expect(aligned.x).toBe(400);
		expect(aligned.y).toBe(80);
		expect(aligned.zoom).toBeCloseTo(0.5);
		const relative = relinkAlignment(
			{ x: 10, y: 10, zoom: 1.25 },
			{ x: 20, y: 30, zoom: 3 },
			null,
			0.5
		);
		expect(relative).toEqual({ x: 20, y: 30, zoom: 1.25 });
	});
});

describe('link session', () => {
	test('only the gesture pane moves the other pane', () => {
		const session = new LinkSession(true);
		session.setBaseline(leftAt(1, 0, 0), { x: 10, y: 10, zoom: 1 });
		expect(session.observe('left', leftAt(1, 5, 0), { left: 0.5, right: 0.5 })).toBeNull();

		session.claim('left');
		const linked = session.observe('left', leftAt(2, 5, 1), { left: 0.5, right: 0.25 });
		expect(linked?.side).toBe('right');
		expect(linked?.view.x).toBeCloseTo(20);
		expect(linked?.view.y).toBeCloseTo(12);
		expect(linked?.view.zoom).toBeCloseTo(1);

		expect(
			session.observe('right', { x: 0, y: 0, zoom: 9 }, { left: 0.5, right: 0.25 })
		).toBeNull();
	});

	test('unlink stops linking and relink resumes from the new centres', () => {
		const session = new LinkSession(true);
		session.setBaseline(leftAt(1), leftAt(1, 50, 50));
		session.unlink();
		session.claim('left');
		expect(session.observe('left', leftAt(3, 20, 20), { left: 0.5, right: 0.5 })).toBeNull();

		const aligned = session.relink(leftAt(2, 20, 20), { x: 80, y: 90, zoom: 4 }, 0.5, 0.25);
		expect(aligned).toEqual({ x: 80, y: 90, zoom: 1 });
		session.claim('left');
		const next = session.observe('left', leftAt(2, 30, 20), { left: 0.5, right: 0.25 });
		expect(next?.view).toEqual({ x: 100, y: 90, zoom: 1 });
	});

	test('a missing mpp uses the relative-zoom fallback while linked', () => {
		const session = new LinkSession(true);
		session.setBaseline(leftAt(1, 0, 0), { x: 5, y: 5, zoom: 1 });
		session.claim('right');
		const linked = session.observe('right', { x: 9, y: 5, zoom: 1.5 }, { left: null, right: 0.5 });
		expect(linked).toEqual({
			side: 'left',
			view: { x: 4, y: 0, zoom: 1.5 }
		});
	});
});
