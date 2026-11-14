import { describe, expect, test } from 'bun:test';
import { formatZoom, readViewportQuery, withViewportQuery } from './viewport-url';

describe('viewer URL', () => {
	test('reads slide, level-0 centre, zoom, patch and panel', () => {
		const params = new URLSearchParams(
			'slide=case-s1&x=1200&y=800.4&zoom=0.125&patch=42&panel=evidence&other=1'
		);
		expect(readViewportQuery(params)).toEqual({
			slide: 'case-s1',
			x: 1200,
			y: 800.4,
			zoom: 0.125,
			patch: '42',
			panel: 'evidence'
		});
	});

	test('drops a non-positive zoom and an unknown panel', () => {
		const params = new URLSearchParams('zoom=-1&panel=heatmap&x=nope');
		expect(readViewportQuery(params)).toEqual({
			slide: null,
			x: null,
			y: null,
			zoom: null,
			patch: null,
			panel: null
		});
	});

	test('patches the query without dropping unrelated keys', () => {
		const url = new URL('http://localhost/cases/abc?panel=report&q=kept');
		const next = withViewportQuery(url, {
			slide: 'abc-s1',
			x: '10',
			y: '20',
			zoom: formatZoom(0.0123456),
			patch: null
		});
		expect(next.searchParams.get('q')).toBe('kept');
		expect(next.searchParams.get('panel')).toBe('report');
		expect(next.searchParams.get('slide')).toBe('abc-s1');
		expect(next.searchParams.get('zoom')).toBe(formatZoom(0.0123456));
		expect(next.searchParams.has('patch')).toBe(false);
		const again = withViewportQuery(next, { x: null, y: null, zoom: null });
		expect(again.searchParams.has('x')).toBe(false);
		expect(again.searchParams.get('slide')).toBe('abc-s1');
	});
});
