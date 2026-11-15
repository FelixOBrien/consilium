import type { components } from '#lib/api/schema.js';

/** Patch score from `POST /api/slides/{id}/heatmap`. The shape lives in the generated client. */
export type HeatmapPatchScore = components['schemas']['HeatmapPatchScore'];

/**
 * Fixed label for the active overlay (F-06.6, F-06.7).
 * The shading is embedding similarity, not a finding and not a diagnosis.
 */
export const SIMILARITY_LABEL = 'Embedding similarity — not a finding';

/**
 * Teal/cyan → gold/amber in OKLab.
 * Lightness rises with the score, and the hue moves on the blue–yellow axis,
 * so the scale stays distinct for protanopia and deuteranopia over pink and
 * purple H&E and still separates by lightness where blue–yellow is weak.
 * Alpha is part of the same fixed scale: low scores stay translucent.
 */
const LOW_RGB: readonly [number, number, number] = [0, 122, 140];
const HIGH_RGB: readonly [number, number, number] = [255, 188, 48];
const LOW_ALPHA = 0.3;
const HIGH_ALPHA = 0.84;
const RAMP_STEPS = 64;

export type Rgba = { r: number; g: number; b: number; a: number };

type Oklab = { l: number; a: number; b: number };

const LOW_LAB = linearToOklab(srgbToLinear(LOW_RGB));
const HIGH_LAB = linearToOklab(srgbToLinear(HIGH_RGB));

const FILL_CACHE = Array.from({ length: RAMP_STEPS + 1 }, (_, step) =>
	rgbaCss(scoreToRgba(step / RAMP_STEPS))
);

/** Min-max to `[0, 1]`. An empty or flat list stays defined (flat scores become 0). */
export function normaliseScores(raw: readonly number[]): number[] {
	if (raw.length === 0) return [];
	let lo = Number.POSITIVE_INFINITY;
	let hi = Number.NEGATIVE_INFINITY;
	for (const value of raw) {
		if (!Number.isFinite(value)) continue;
		if (value < lo) lo = value;
		if (value > hi) hi = value;
	}
	if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi === lo) {
		return raw.map(() => 0);
	}
	const span = hi - lo;
	return raw.map((value) => {
		if (!Number.isFinite(value) || value === lo) return 0;
		if (value === hi) return 1;
		const score = (value - lo) / span;
		if (score <= 0) return 0;
		if (score >= 1) return 1;
		return score;
	});
}

/** Same geometry, with scores forced onto the fixed 0–1 scale. */
export function normalisePatches(patches: readonly HeatmapPatchScore[]): HeatmapPatchScore[] {
	const scores = normaliseScores(patches.map((patch) => patch.score));
	return patches.map((patch, index) => ({
		x: patch.x,
		y: patch.y,
		size: patch.size,
		score: scores[index] ?? 0
	}));
}

/** Perceptual colour and alpha for one normalised score. Endpoints are exact. */
export function scoreToRgba(score: number): Rgba {
	const t = clamp01(score);
	if (t <= 0) return { r: LOW_RGB[0], g: LOW_RGB[1], b: LOW_RGB[2], a: LOW_ALPHA };
	if (t >= 1) return { r: HIGH_RGB[0], g: HIGH_RGB[1], b: HIGH_RGB[2], a: HIGH_ALPHA };
	const lab = {
		l: LOW_LAB.l + (HIGH_LAB.l - LOW_LAB.l) * t,
		a: LOW_LAB.a + (HIGH_LAB.a - LOW_LAB.a) * t,
		b: LOW_LAB.b + (HIGH_LAB.b - LOW_LAB.b) * t
	};
	const rgb = linearToSrgb(oklabToLinear(lab));
	return {
		r: rgb[0],
		g: rgb[1],
		b: rgb[2],
		a: LOW_ALPHA + (HIGH_ALPHA - LOW_ALPHA) * t
	};
}

/** Cached CSS colour. The drawer uses this so thousands of patches share a handful of fills. */
export function fillForScore(score: number): string {
	const index = Math.round(clamp01(score) * RAMP_STEPS);
	return FILL_CACHE[index] ?? FILL_CACHE[0] ?? 'rgba(0, 122, 140, 0.3)';
}

export function rgbaCss(color: Rgba): string {
	const alpha = Math.round(color.a * 1000) / 1000;
	return `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`;
}

/** OKLab lightness of a normalised score. Higher scores are lighter. */
export function scoreLightness(score: number): number {
	const t = clamp01(score);
	return LOW_LAB.l + (HIGH_LAB.l - LOW_LAB.l) * t;
}

/** OKLab b (blue ← 0 → yellow) of a normalised score. */
export function scoreYellowBlue(score: number): number {
	const t = clamp01(score);
	return LOW_LAB.b + (HIGH_LAB.b - LOW_LAB.b) * t;
}

function clamp01(score: number): number {
	if (!Number.isFinite(score) || score <= 0) return 0;
	if (score >= 1) return 1;
	return score;
}

function srgbToLinear(rgb: readonly [number, number, number]): [number, number, number] {
	return [linearChannel(rgb[0]), linearChannel(rgb[1]), linearChannel(rgb[2])];
}

function linearChannel(channel: number): number {
	const value = channel / 255;
	return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

function linearToSrgb(rgb: readonly [number, number, number]): [number, number, number] {
	return [srgbChannel(rgb[0]), srgbChannel(rgb[1]), srgbChannel(rgb[2])];
}

function srgbChannel(channel: number): number {
	const value = channel <= 0.0031308 ? 12.92 * channel : 1.055 * channel ** (1 / 2.4) - 0.055;
	return Math.round(Math.min(1, Math.max(0, value)) * 255);
}

function linearToOklab(rgb: readonly [number, number, number]): Oklab {
	const l = Math.cbrt(0.4122214708 * rgb[0] + 0.5363325363 * rgb[1] + 0.0514459929 * rgb[2]);
	const m = Math.cbrt(0.2119034982 * rgb[0] + 0.6806995451 * rgb[1] + 0.1073969566 * rgb[2]);
	const s = Math.cbrt(0.0883024619 * rgb[0] + 0.2817188376 * rgb[1] + 0.6299787005 * rgb[2]);
	return {
		l: 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
		a: 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
		b: 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
	};
}

function oklabToLinear(lab: Oklab): [number, number, number] {
	const l = lab.l + 0.3963377774 * lab.a + 0.2158037573 * lab.b;
	const m = lab.l - 0.1055613458 * lab.a - 0.0638541728 * lab.b;
	const s = lab.l - 0.0894841775 * lab.a - 1.291485548 * lab.b;
	const l3 = l * l * l;
	const m3 = m * m * m;
	const s3 = s * s * s;
	return [
		4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
		-1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
		-0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3
	];
}
