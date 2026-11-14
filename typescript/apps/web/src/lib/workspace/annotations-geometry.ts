import type { ViewerAnnotationShape } from './overlay-layers.js';

/** Label limit from the annotation model. */
export const ANNOTATION_LABEL_MAX = 80;

export type SlideBounds = {
	width: number;
	height: number;
};

export type Level0Rect = {
	x: number;
	y: number;
	width: number;
	height: number;
};

export type Level0Point = {
	x: number;
	y: number;
};

export type DrawnGeometry =
	| { kind: 'rect'; x: number; y: number; w: number; h: number }
	| { kind: 'point'; x: number; y: number };

export type RoundedGeometry =
	| { ok: true; kind: 'rect'; geometry: Level0Rect }
	| { ok: true; kind: 'point'; geometry: Level0Point }
	| { ok: false; message: string };

/** Fields the panel needs from `Annotation`. The generated type satisfies this. */
export type AnnotationLike = {
	id: string;
	slide_id: string;
	kind: 'rect' | 'point';
	label: string;
	note: string | null;
	created_at: string;
	can_edit: boolean;
	author: { id: string; name: string; is_synthetic: boolean };
	geometry: { x: number; y: number; width?: number; height?: number };
};

const TOO_SMALL = 'Draw a larger rectangle. The mark needs at least one pixel on each side.';
const OUTSIDE = 'That mark sits outside the slide. Draw it on the tissue and try again.';

/**
 * Own marks follow the acting pathologist. `can_edit` is the server's answer for
 * whoever was acting when the list was loaded, so a roster change rechecks the author.
 */
export function annotationIsOwn(annotation: AnnotationLike, meId: string | null): boolean {
	if (meId) return annotation.author.id === meId;
	return annotation.can_edit;
}

export function sortNewestFirst<T extends { created_at: string; id: string }>(
	items: readonly T[]
): T[] {
	return [...items].sort((a, b) => {
		if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1;
		return a.id < b.id ? 1 : -1;
	});
}

export function notePreview(note: string | null, max = 80): string | null {
	if (!note) return null;
	const flat = note.replace(/\s+/g, ' ').trim();
	if (!flat) return null;
	if (flat.length <= max) return flat;
	return `${flat.slice(0, max - 1)}…`;
}

export function kindLabel(kind: 'rect' | 'point'): 'Rectangle' | 'Point' {
	return kind === 'rect' ? 'Rectangle' : 'Point';
}

export function formatAnnotationTime(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	return new Intl.DateTimeFormat('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23',
		timeZone: 'UTC'
	}).format(date);
}

export function roundRect(
	rect: { x: number; y: number; w: number; h: number },
	bounds?: SlideBounds | null
): Extract<RoundedGeometry, { kind: 'rect' } | { ok: false }> {
	if (![rect.x, rect.y, rect.w, rect.h].every(Number.isFinite)) {
		return { ok: false, message: OUTSIDE };
	}
	return placeRect(
		{
			x: Math.round(rect.x),
			y: Math.round(rect.y),
			width: Math.round(rect.w),
			height: Math.round(rect.h)
		},
		bounds
	);
}

export function roundPoint(
	point: { x: number; y: number },
	bounds?: SlideBounds | null
): Extract<RoundedGeometry, { kind: 'point' } | { ok: false }> {
	if (![point.x, point.y].every(Number.isFinite)) return { ok: false, message: OUTSIDE };
	let x = Math.round(point.x);
	let y = Math.round(point.y);
	const box = normalBounds(bounds);
	if (box) {
		if (x < 0 || y < 0 || x >= box.width || y >= box.height) {
			x = Math.min(Math.max(0, x), box.width - 1);
			y = Math.min(Math.max(0, y), box.height - 1);
		}
	} else if (x < 0 || y < 0) {
		return { ok: false, message: OUTSIDE };
	}
	return { ok: true, kind: 'point', geometry: { x, y } };
}

export function roundDrawn(geom: DrawnGeometry, bounds?: SlideBounds | null): RoundedGeometry {
	if (geom.kind === 'rect') return roundRect(geom, bounds);
	return roundPoint(geom, bounds);
}

export function toViewerShape(
	annotation: AnnotationLike,
	meId: string | null,
	selectedId: string | null
): ViewerAnnotationShape {
	const own = annotationIsOwn(annotation, meId);
	const selected = annotation.id === selectedId;
	if (annotation.kind === 'point' || !hasSize(annotation.geometry)) {
		return {
			id: annotation.id,
			kind: 'point',
			x: annotation.geometry.x,
			y: annotation.geometry.y,
			label: annotation.label,
			isOwn: own,
			selected
		};
	}
	return {
		id: annotation.id,
		kind: 'rect',
		x: annotation.geometry.x,
		y: annotation.geometry.y,
		w: annotation.geometry.width,
		h: annotation.geometry.height,
		label: annotation.label,
		isOwn: own,
		selected
	};
}

export function draftViewerShape(
	kind: 'rect' | 'point',
	geometry: Level0Rect | Level0Point,
	label: string
): ViewerAnnotationShape {
	if (kind === 'rect' && 'width' in geometry) {
		return {
			id: 'draft',
			kind: 'rect',
			x: geometry.x,
			y: geometry.y,
			w: geometry.width,
			h: geometry.height,
			label: label.trim(),
			isOwn: true,
			selected: true
		};
	}
	return {
		id: 'draft',
		kind: 'point',
		x: geometry.x,
		y: geometry.y,
		label: label.trim(),
		isOwn: true,
		selected: true
	};
}

export function regionHandoff(annotation: AnnotationLike): {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
} | null {
	if (annotation.kind !== 'rect' || !hasSize(annotation.geometry)) return null;
	return {
		slideId: annotation.slide_id,
		x: annotation.geometry.x,
		y: annotation.geometry.y,
		width: annotation.geometry.width,
		height: annotation.geometry.height
	};
}

export function flyTarget(annotation: AnnotationLike): {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
} {
	const region = regionHandoff(annotation);
	if (region) return region;
	const span = 512;
	return {
		slideId: annotation.slide_id,
		x: annotation.geometry.x - span / 2,
		y: annotation.geometry.y - span / 2,
		width: span,
		height: span
	};
}

export function geometrySummary(
	kind: 'rect' | 'point',
	geometry: Level0Rect | Level0Point | null
): string | null {
	if (!geometry) return null;
	if (kind === 'rect' && 'width' in geometry) {
		return `Rectangle, ${geometry.width} × ${geometry.height} px at (${geometry.x}, ${geometry.y}), level-0.`;
	}
	return `Point at (${geometry.x}, ${geometry.y}), level-0.`;
}

function placeRect(
	rect: Level0Rect,
	bounds?: SlideBounds | null
): Extract<RoundedGeometry, { kind: 'rect' } | { ok: false }> {
	let { x, y, width, height } = rect;
	if (width < 1 || height < 1) return { ok: false, message: TOO_SMALL };
	const box = normalBounds(bounds);
	if (box) {
		if (x >= box.width || y >= box.height || x + width <= 0 || y + height <= 0) {
			return { ok: false, message: OUTSIDE };
		}
		x = Math.min(Math.max(0, x), box.width - 1);
		y = Math.min(Math.max(0, y), box.height - 1);
		width = Math.min(width, box.width - x);
		height = Math.min(height, box.height - y);
		if (width < 1 || height < 1) return { ok: false, message: OUTSIDE };
	} else if (x < 0 || y < 0) {
		return { ok: false, message: OUTSIDE };
	}
	return { ok: true, kind: 'rect', geometry: { x, y, width, height } };
}

function normalBounds(bounds?: SlideBounds | null): SlideBounds | null {
	if (!bounds || !Number.isFinite(bounds.width) || !Number.isFinite(bounds.height)) return null;
	const width = Math.round(bounds.width);
	const height = Math.round(bounds.height);
	if (width < 1 || height < 1) return null;
	return { width, height };
}

function hasSize(geometry: { width?: number; height?: number }): geometry is {
	width: number;
	height: number;
} {
	return (
		typeof geometry.width === 'number' &&
		typeof geometry.height === 'number' &&
		geometry.width > 0 &&
		geometry.height > 0
	);
}
