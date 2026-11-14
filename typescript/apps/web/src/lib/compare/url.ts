import type { PaneView } from './scale.js';

/** Shareable `/compare` query. Coordinates are level-0 pixels (F-03.5). */
export type CompareQuery = {
	left: string | null;
	right: string | null;
	lx: number | null;
	ly: number | null;
	lzoom: number | null;
	rx: number | null;
	ry: number | null;
	rzoom: number | null;
	/** `sync=0` unlinks. Any other value, including omission, stays linked. */
	sync: boolean;
};

const COMPARE_PATH = '/compare?left=<slideId>&right=<slideId>';

export function missingCompareHint(): string {
	return COMPARE_PATH;
}

export function parseCompareQuery(params: { get(name: string): string | null }): CompareQuery {
	return {
		left: text(params.get('left')),
		right: text(params.get('right')),
		lx: finite(params.get('lx')),
		ly: finite(params.get('ly')),
		lzoom: positive(params.get('lzoom')),
		rx: finite(params.get('rx')),
		ry: finite(params.get('ry')),
		rzoom: positive(params.get('rzoom')),
		sync: params.get('sync') !== '0'
	};
}

export function writeCompareQuery(current: { href: string }, query: CompareQuery): URL {
	const url = new URL(current.href);
	setText(url.searchParams, 'left', query.left);
	setText(url.searchParams, 'right', query.right);
	setNumber(url.searchParams, 'lx', query.lx, 4);
	setNumber(url.searchParams, 'ly', query.ly, 4);
	setNumber(url.searchParams, 'lzoom', query.lzoom, 6);
	setNumber(url.searchParams, 'rx', query.rx, 4);
	setNumber(url.searchParams, 'ry', query.ry, 4);
	setNumber(url.searchParams, 'rzoom', query.rzoom, 6);
	url.searchParams.set('sync', query.sync ? '1' : '0');
	return url;
}

export function hasSlidePair(
	query: CompareQuery
): query is CompareQuery & { left: string; right: string } {
	return query.left != null && query.right != null;
}

/** A locus is only marked when both level-0 coordinates are present. */
export function locus(x: number | null, y: number | null): { x: number; y: number } | null {
	if (x == null || y == null) return null;
	return { x, y };
}

export function queryFromViews(
	slides: { left: string; right: string },
	left: PaneView | null,
	right: PaneView | null,
	sync: boolean,
	fallback: CompareQuery
): CompareQuery {
	return {
		left: slides.left,
		right: slides.right,
		lx: left?.x ?? fallback.lx,
		ly: left?.y ?? fallback.ly,
		lzoom: left?.zoom ?? fallback.lzoom,
		rx: right?.x ?? fallback.rx,
		ry: right?.y ?? fallback.ry,
		rzoom: right?.zoom ?? fallback.rzoom,
		sync
	};
}

/** Search string for S-02, without the leading `?`. */
export function caseViewSearch(slideId: string, view: PaneView | null): string {
	const params = new URLSearchParams();
	params.set('slide', slideId);
	if (view) {
		params.set('x', trimFixed(view.x, 4));
		params.set('y', trimFixed(view.y, 4));
		params.set('zoom', trimFixed(view.zoom, 6));
	}
	return params.toString();
}

function text(value: string | null): string | null {
	const trimmed = value?.trim() ?? '';
	return trimmed.length > 0 ? trimmed : null;
}

function finite(value: string | null): number | null {
	if (value == null || value.trim() === '') return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
}

function positive(value: string | null): number | null {
	const parsed = finite(value);
	return parsed != null && parsed > 0 ? parsed : null;
}

function setText(params: URLSearchParams, key: string, value: string | null): void {
	if (value == null || value.trim() === '') params.delete(key);
	else params.set(key, value);
}

function setNumber(
	params: URLSearchParams,
	key: string,
	value: number | null,
	digits: number
): void {
	if (value == null || !Number.isFinite(value)) params.delete(key);
	else params.set(key, trimFixed(value, digits));
}

function trimFixed(value: number, digits: number): string {
	const fixed = value.toFixed(digits);
	if (!fixed.includes('.')) return fixed;
	return fixed.replace(/\.?0+$/, '');
}
