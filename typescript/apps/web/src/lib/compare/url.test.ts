import { describe, expect, test } from 'bun:test';
import {
	COMPARE_FRAMING,
	MISSING_COMPARE_BODY,
	OPEN_CASE_LABEL,
	PRECEDENT_LABEL,
	RELATIVE_SCALE_NOTE,
	compareCopyAvoidsDiagnosis
} from './copy.js';
import {
	hasSlidePair,
	locus,
	missingCompareHint,
	parseCompareQuery,
	writeCompareQuery
} from './url.js';

describe('compare URL state', () => {
	test('round-trips slide ids, viewports and sync', () => {
		const query = {
			left: 'FX-B042C-s1',
			right: 'FX-S018A-s1',
			lx: 682.5,
			ly: 512,
			lzoom: 1.25,
			rx: 853.25,
			ry: 682,
			rzoom: 0.5,
			sync: false
		};
		const url = writeCompareQuery(new URL('http://localhost/compare?panel=keep'), query);
		expect(url.searchParams.get('panel')).toBe('keep');
		expect(url.searchParams.get('sync')).toBe('0');
		expect(parseCompareQuery(url.searchParams)).toEqual(query);
		expect(hasSlidePair(query)).toBe(true);
	});

	test('defaults sync on and drops blank or invalid numbers', () => {
		const params = new URLSearchParams(
			'left=%20FX-B042C-s1&right=&lx=nope&ly=10&lzoom=0&rx=-4&ry=&rzoom=-1'
		);
		expect(parseCompareQuery(params)).toEqual({
			left: 'FX-B042C-s1',
			right: null,
			lx: null,
			ly: 10,
			lzoom: null,
			rx: -4,
			ry: null,
			rzoom: null,
			sync: true
		});
		const written = writeCompareQuery(new URL('http://localhost/compare?sync=0'), {
			left: 'FX-B042C-s1',
			right: null,
			lx: null,
			ly: 10,
			lzoom: null,
			rx: -4,
			ry: null,
			rzoom: null,
			sync: true
		});
		expect(written.searchParams.get('sync')).toBe('1');
		expect(written.searchParams.has('right')).toBe(false);
		expect(written.searchParams.has('lzoom')).toBe(false);
		expect(parseCompareQuery(written.searchParams).sync).toBe(true);
	});

	test('marks a locus only when both coordinates are present', () => {
		expect(locus(12, 8)).toEqual({ x: 12, y: 8 });
		expect(locus(12, null)).toBeNull();
		expect(locus(null, 8)).toBeNull();
		expect(hasSlidePair(parseCompareQuery(new URLSearchParams('left=a')))).toBe(false);
	});

	test('names the URL a caller should open', () => {
		expect(missingCompareHint()).toBe('/compare?left=<slideId>&right=<slideId>');
	});

	test('visible copy does not treat the slides as the same diagnosis', () => {
		for (const text of [
			OPEN_CASE_LABEL,
			PRECEDENT_LABEL,
			COMPARE_FRAMING,
			RELATIVE_SCALE_NOTE,
			MISSING_COMPARE_BODY
		]) {
			expect(compareCopyAvoidsDiagnosis(text)).toBe(true);
		}
	});
});
