/** Shareable case-viewer query (`slide`, `x`, `y`, `zoom`, `panel`, `patch`). */

export const PANEL_IDS = ['report', 'evidence', 'consult', 'annotations'] as const;

export type PanelId = (typeof PANEL_IDS)[number];

export type ViewportQuery = {
	slide: string | null;
	x: number | null;
	y: number | null;
	zoom: number | null;
	patch: string | null;
	panel: PanelId | null;
};

export type ViewportQueryPatch = Partial<
	Record<'slide' | 'x' | 'y' | 'zoom' | 'patch' | 'panel', string | null>
>;

export function isPanelId(value: string | null): value is PanelId {
	return value !== null && (PANEL_IDS as readonly string[]).includes(value);
}

export function formatLevel0(value: number): string {
	return String(Math.round(value));
}

/** Stable URL form for CSS pixels per level-0 pixel. */
export function formatZoom(zoom: number): string {
	if (!Number.isFinite(zoom) || zoom <= 0) return '';
	return String(Number(zoom.toPrecision(6)));
}

export function readViewportQuery(params: { get(name: string): string | null }): ViewportQuery {
	const panel = params.get('panel');
	const zoom = finiteNumber(params.get('zoom'));
	return {
		slide: nonempty(params.get('slide')),
		x: finiteNumber(params.get('x')),
		y: finiteNumber(params.get('y')),
		zoom: zoom != null && zoom > 0 ? zoom : null,
		patch: nonempty(params.get('patch')),
		panel: isPanelId(panel) ? panel : null
	};
}

export function withViewportQuery(url: URL, changes: ViewportQueryPatch): URL {
	const next = new URL(url.href);
	for (const [key, value] of Object.entries(changes)) {
		if (value == null || value === '') next.searchParams.delete(key);
		else next.searchParams.set(key, value);
	}
	return next;
}

function nonempty(value: string | null): string | null {
	const trimmed = value?.trim() ?? '';
	return trimmed || null;
}

function finiteNumber(value: string | null): number | null {
	if (value == null || value.trim() === '') return null;
	const number = Number(value);
	return Number.isFinite(number) ? number : null;
}
