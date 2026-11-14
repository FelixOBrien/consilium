/**
 * Pure evidence-panel model (S-04 / F-05).
 *
 * Scores are relative within one response. Callers may show a tier and a bar.
 * They must not show the number, a percentage, or a probability.
 */

import type { components } from '#lib/api/schema.js';
import { SPECIALTIES, specialtyLabel } from '#lib/worklist/query.js';
import type { ViewerSearchHit } from './overlay-layers.js';
import { formatZoom } from './viewport-url.js';

export type PeekPatch = {
	id: string;
	slide_id: string;
	x: number;
	y: number;
	size?: number;
};

export type SearchResponse = components['schemas']['SearchResponse'];
export type SlideScopeResponse = components['schemas']['SlideScopeResponse'];
export type CaseHit = components['schemas']['CaseHit'];
export type PatchHit = components['schemas']['PatchHit'];
export type Passage = components['schemas']['Passage'];
export type PatchSearchRequest = components['schemas']['PatchSearchRequest'];
export type ReportSearchRequest = components['schemas']['ReportSearchRequest'];
export type SearchFilters = components['schemas']['SearchFilters'];
export type Specialty = components['schemas']['Specialty'];
export type SearchMode = 'tissue' | 'reports';
export type SearchScope = 'corpus' | 'slide';

/** CSS pixels the open-case viewer should give a stored patch. */
export const PATCH_FRAME_PX = 240;
export const EVIDENCE_LIMIT = 20;
/** First text search past this is treated as an encoder that is still warming up. */
export const TEXT_ENCODER_WARMUP_MS = 3000;

export type EvidenceFilters = {
	specialty: Specialty | null;
	icd10Prefix: string;
	samePatient: boolean;
};

export type EvidenceIntent =
	| {
			kind: 'patch';
			patchId: string;
			slideId: string;
			x: number;
			y: number;
			size: number;
	  }
	| {
			kind: 'region';
			slideId: string;
			x: number;
			y: number;
			width: number;
			height: number;
	  }
	| { kind: 'report_text'; text: string };

export type ActiveQuery =
	| {
			kind: 'patch';
			patchId: string;
			slideId: string;
			x: number;
			y: number;
			size: number;
	  }
	| {
			kind: 'region';
			slideId: string;
			x: number;
			y: number;
			width: number;
			height: number;
	  }
	| { kind: 'slide'; slideId: string }
	| { kind: 'tissue-text'; text: string }
	| { kind: 'report-text'; text: string };

export type ScoreTier = 'closest' | 'strong' | 'related' | 'distant';

export type PresentedScore = {
	tier: ScoreTier;
	label: string;
	/** Bar length in quarters. Never a displayed percentage. */
	bar: 1 | 2 | 3 | 4;
};

export type TextSegment = { text: string; marked: boolean };

export type QueryPresentation = {
	kicker: string;
	label: string;
	thumbnail: 'patch' | 'slide' | null;
	slideId: string | null;
	patchId: string | null;
};

export type PresentedPassage = {
	section: string;
	segments: TextSegment[];
};

export type PresentedCase = {
	caseId: string;
	patientId: string;
	patientLabel: string;
	syntheticLinkage: boolean;
	samePatient: boolean;
	specialty: string;
	icd10: string | null;
	conclusion: string | null;
	authorName: string;
	authorSynthetic: boolean;
	score: PresentedScore;
	matchedBy: string[];
	patches: PatchHit[];
	patchCountLabel: string | null;
	passage: PresentedPassage | null;
	openQuery: string;
	peekPatch: PeekPatch | undefined;
};

export type RegionFlyTarget = {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
	markPatch: { id: string; x: number; y: number; size: number };
};

export type PresentedRegion = {
	id: string;
	label: string;
	slideId: string;
	thumbnailUrl: string;
	score: PresentedScore;
	fly: RegionFlyTarget;
};

export type BuiltSearch =
	| { endpoint: 'patches'; body: PatchSearchRequest; scope: SearchScope }
	| { endpoint: 'reports'; body: ReportSearchRequest; scope: 'corpus' };

export type SearchFailure =
	{ kind: 'no-tissue'; message: string } | { kind: 'error'; message: string };

const TIER_LABEL: Record<ScoreTier, string> = {
	closest: 'Closest',
	strong: 'Strong',
	related: 'Related',
	distant: 'Distant'
};

const TIER_BAR: Record<ScoreTier, 1 | 2 | 3 | 4> = {
	distant: 1,
	related: 2,
	strong: 3,
	closest: 4
};

const MATCH_LABEL = {
	morphology: 'Tissue',
	keyword: 'Keyword',
	semantic: 'Meaning'
} as const;

const SECTION_LABEL: Record<Passage['section'], string> = {
	clinical_history: 'Clinical history',
	gross_description: 'Gross description',
	microscopic_description: 'Microscopic description',
	conclusion: 'Conclusion',
	additional_info: 'Additional information',
	body: 'Report'
};

export function emptyFilters(): EvidenceFilters {
	return { specialty: null, icd10Prefix: '', samePatient: false };
}

export function sameFilters(a: EvidenceFilters, b: EvidenceFilters): boolean {
	return (
		a.specialty === b.specialty &&
		a.icd10Prefix === b.icd10Prefix &&
		a.samePatient === b.samePatient
	);
}

export function filtersActive(filters: EvidenceFilters): boolean {
	return filters.specialty != null || filters.icd10Prefix.trim() !== '' || filters.samePatient;
}

export function parseSpecialty(value: string): Specialty | null {
	return (SPECIALTIES as readonly string[]).includes(value) ? (value as Specialty) : null;
}

export function filtersKey(filters: EvidenceFilters): string {
	return `${filters.specialty ?? ''}|${filters.icd10Prefix}|${filters.samePatient ? '1' : '0'}`;
}

export function queryFromIntent(intent: EvidenceIntent): ActiveQuery {
	if (intent.kind === 'report_text') {
		return { kind: 'report-text', text: intent.text.trim() };
	}
	if (intent.kind === 'patch') {
		return {
			kind: 'patch',
			patchId: intent.patchId,
			slideId: intent.slideId,
			x: intent.x,
			y: intent.y,
			size: intent.size
		};
	}
	return {
		kind: 'region',
		slideId: intent.slideId,
		x: intent.x,
		y: intent.y,
		width: intent.width,
		height: intent.height
	};
}

export function queryMode(query: ActiveQuery): SearchMode {
	return query.kind === 'report-text' ? 'reports' : 'tissue';
}

export function isTextQuery(query: ActiveQuery): boolean {
	return query.kind === 'tissue-text' || query.kind === 'report-text';
}

/** Slide scope is only valid for a patch, a region, or a tissue description (F-05.9). */
export function querySupportsSlideScope(query: ActiveQuery): boolean {
	return query.kind === 'patch' || query.kind === 'region' || query.kind === 'tissue-text';
}

export function effectiveScope(query: ActiveQuery, requested: SearchScope): SearchScope {
	return requested === 'slide' && querySupportsSlideScope(query) ? 'slide' : 'corpus';
}

export function slideScopeUnavailableReason(query: ActiveQuery): string | null {
	if (querySupportsSlideScope(query)) return null;
	if (query.kind === 'slide') {
		return 'Cases like this slide searches other signed-out cases. Select tissue, draw a region, or describe a pattern to search this slide.';
	}
	return 'Report search looks across signed-out reports. This-slide scope applies to a tissue query.';
}

export function shouldWarnEncoderWarmup(firstTextQuery: boolean, elapsedMs: number): boolean {
	return firstTextQuery && elapsedMs >= TEXT_ENCODER_WARMUP_MS;
}

export function toSearchFilters(
	filters: EvidenceFilters,
	patientId: string | null
): SearchFilters | null {
	const specialty = filters.specialty ? [filters.specialty] : null;
	const icd10 = filters.icd10Prefix.trim().toUpperCase();
	const patient = filters.samePatient && patientId ? patientId : null;
	if (!specialty && !icd10 && !patient) return null;
	return {
		specialty,
		icd10_prefix: icd10 || null,
		patient_id: patient
	};
}

function patchIdNumber(value: string): number | null {
	if (!/^\d+$/.test(value)) return null;
	const id = Number(value);
	if (!Number.isSafeInteger(id) || id < 1) return null;
	return id;
}

/**
 * Build the search call for the active query.
 * "Cases like this slide" is Q3: `POST /api/search/patches` with the open slide id.
 */
export function buildSearch(input: {
	query: ActiveQuery;
	scope: SearchScope;
	filters: EvidenceFilters;
	contextCaseId: string;
	patientId: string | null;
}): BuiltSearch | { error: string } {
	const filters = toSearchFilters(input.filters, input.patientId);
	if (input.query.kind === 'report-text') {
		const text = input.query.text.trim();
		if (!text) return { error: 'Enter report text to search.' };
		return {
			endpoint: 'reports',
			scope: 'corpus',
			body: {
				text,
				mode: 'hybrid',
				context_case_id: input.contextCaseId,
				filters,
				limit: EVIDENCE_LIMIT
			}
		};
	}

	const scope = effectiveScope(input.query, input.scope);
	const body: PatchSearchRequest = {
		context_case_id: input.contextCaseId,
		scope,
		filters,
		limit: EVIDENCE_LIMIT
	};
	if (input.query.kind === 'patch') {
		const patchId = patchIdNumber(input.query.patchId);
		if (patchId == null) return { error: 'That patch cannot be searched.' };
		body.patch_id = patchId;
	} else if (input.query.kind === 'region') {
		const width = Math.round(input.query.width);
		const height = Math.round(input.query.height);
		if (width < 1 || height < 1) return { error: 'The region is empty.' };
		body.region = {
			slide_id: input.query.slideId,
			x: Math.round(input.query.x),
			y: Math.round(input.query.y),
			width,
			height
		};
	} else if (input.query.kind === 'slide') {
		if (!input.query.slideId) return { error: 'Open a slide before searching for similar cases.' };
		body.slide_id = input.query.slideId;
	} else {
		const text = input.query.text.trim();
		if (!text) return { error: 'Describe the tissue to search.' };
		body.text = text;
	}
	return { endpoint: 'patches', body, scope };
}

export function presentQuery(query: ActiveQuery): QueryPresentation {
	switch (query.kind) {
		case 'patch':
			return {
				kicker: 'Tissue · selected patch',
				label: 'Selected patch',
				thumbnail: 'patch',
				slideId: query.slideId,
				patchId: query.patchId
			};
		case 'region':
			return {
				kicker: 'Tissue · selected region',
				label: 'Selected region',
				thumbnail: 'slide',
				slideId: query.slideId,
				patchId: null
			};
		case 'slide':
			return {
				kicker: 'Tissue · this slide',
				label: 'This slide',
				thumbnail: 'slide',
				slideId: query.slideId,
				patchId: null
			};
		case 'tissue-text':
			return {
				kicker: 'Tissue · description',
				label: query.text,
				thumbnail: null,
				slideId: null,
				patchId: null
			};
		case 'report-text':
			return {
				kicker: 'Reports · text',
				label: query.text,
				thumbnail: null,
				slideId: null,
				patchId: null
			};
	}
}

export function patchThumbnailUrl(patchId: string): string {
	return `/api/patches/${encodeURIComponent(patchId)}/thumbnail`;
}

function clamp01(score: number): number {
	if (!Number.isFinite(score)) return 0;
	return Math.min(1, Math.max(0, score));
}

function tierFor(score: number): ScoreTier {
	if (score >= 0.85) return 'closest';
	if (score >= 0.6) return 'strong';
	if (score >= 0.35) return 'related';
	return 'distant';
}

/** Relative indicator for a response-normalised score. The label has no digits. */
export function presentScore(score: number): PresentedScore {
	const tier = tierFor(clamp01(score));
	return { tier, label: TIER_LABEL[tier], bar: TIER_BAR[tier] };
}

/** Rank within a this-slide list. Raw cosine similarity is not shown. */
export function presentRankScore(index: number): PresentedScore {
	if (index <= 0) return presentScore(1);
	if (index === 1) return presentScore(0.7);
	if (index === 2) return presentScore(0.45);
	return presentScore(0.2);
}

export function passageSegments(
	text: string,
	highlights: readonly (readonly [number, number])[]
): TextSegment[] {
	const ranges: { start: number; end: number }[] = [];
	for (const [rawStart, rawEnd] of highlights) {
		if (!Number.isFinite(rawStart) || !Number.isFinite(rawEnd)) continue;
		const start = Math.max(0, Math.min(text.length, Math.floor(rawStart)));
		const end = Math.max(start, Math.min(text.length, Math.floor(rawEnd)));
		if (end > start) ranges.push({ start, end });
	}
	ranges.sort((a, b) => a.start - b.start || a.end - b.end);
	const merged: { start: number; end: number }[] = [];
	for (const range of ranges) {
		const last = merged.at(-1);
		if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
		else merged.push({ ...range });
	}
	const segments: TextSegment[] = [];
	let cursor = 0;
	for (const range of merged) {
		if (range.start > cursor) {
			segments.push({ text: text.slice(cursor, range.start), marked: false });
		}
		segments.push({ text: text.slice(range.start, range.end), marked: true });
		cursor = range.end;
	}
	if (cursor < text.length) segments.push({ text: text.slice(cursor), marked: false });
	if (segments.length === 0) segments.push({ text, marked: false });
	return segments;
}

export function presentPassage(passage: Passage): PresentedPassage {
	return {
		section: SECTION_LABEL[passage.section],
		segments: passageSegments(passage.text, passage.highlights)
	};
}

export function matchedByLabels(
	kinds: readonly ('morphology' | 'keyword' | 'semantic')[]
): string[] {
	return kinds.map((kind) => MATCH_LABEL[kind]);
}

export function patchCountLabel(count: number): string | null {
	if (count < 1) return null;
	return count === 1 ? '1 matching patch' : `${count} matching patches`;
}

/** Level-0 centre and zoom so S-02 opens on the stored patch. */
export function caseOpenQuery(
	patch: Pick<PatchHit, 'slide_id' | 'x' | 'y' | 'size' | 'patch_id'>
): string {
	const params = new URLSearchParams();
	params.set('slide', patch.slide_id);
	params.set('x', String(Math.round(patch.x + patch.size / 2)));
	params.set('y', String(Math.round(patch.y + patch.size / 2)));
	params.set('zoom', formatZoom(PATCH_FRAME_PX / patch.size));
	params.set('patch', String(patch.patch_id));
	return params.toString();
}

function nonempty(value: string | null | undefined): string | null {
	const text = value?.trim() ?? '';
	return text || null;
}

/**
 * Signed-out precedent only. Open cases contribute no conclusion, ICD-10, or passage.
 */
export function presentCase(hit: CaseHit): PresentedCase {
	const signedOut = hit.case.status === 'signed_out';
	const patches = signedOut ? hit.patches.slice(0, 3) : [];
	const primary = patches[0];
	return {
		caseId: hit.case.id,
		patientId: hit.case.patient.id,
		patientLabel: hit.case.patient.display_label,
		syntheticLinkage: hit.case.patient.is_synthetic_linkage,
		samePatient: hit.same_patient,
		specialty: specialtyLabel(hit.case.specialty),
		icd10: signedOut ? nonempty(hit.case.icd10) : null,
		conclusion: signedOut ? nonempty(hit.case.conclusion_line) : null,
		authorName: hit.author.name,
		authorSynthetic: hit.author.is_synthetic,
		score: presentScore(hit.score),
		matchedBy: matchedByLabels(hit.matched_by),
		patches,
		patchCountLabel: signedOut ? patchCountLabel(hit.patch_match_count) : null,
		passage: signedOut && hit.passage ? presentPassage(hit.passage) : null,
		openQuery: primary ? caseOpenQuery(primary) : '',
		peekPatch: primary
			? {
					id: String(primary.patch_id),
					slide_id: primary.slide_id,
					x: primary.x,
					y: primary.y,
					size: primary.size
				}
			: undefined
	};
}

/** Drop the open case and anything that is not signed out (F-05.1). */
export function visibleCaseHits(hits: readonly CaseHit[], contextCaseId: string): CaseHit[] {
	return hits.filter((hit) => hit.case.id !== contextCaseId && hit.case.status === 'signed_out');
}

export function consultCaseIds(hits: readonly CaseHit[]): string[] {
	const ids: string[] = [];
	const seen = new Set<string>();
	for (const hit of hits) {
		if (hit.case.status !== 'signed_out') continue;
		if (seen.has(hit.case.id)) continue;
		seen.add(hit.case.id);
		ids.push(hit.case.id);
	}
	return ids;
}

export function regionFlyTarget(patch: PatchHit): RegionFlyTarget {
	return {
		slideId: patch.slide_id,
		x: patch.x,
		y: patch.y,
		width: patch.size,
		height: patch.size,
		markPatch: {
			id: String(patch.patch_id),
			x: patch.x,
			y: patch.y,
			size: patch.size
		}
	};
}

export function searchMarkers(patches: readonly PatchHit[]): ViewerSearchHit[] {
	return patches.map((patch, index) => ({
		id: String(patch.patch_id),
		x: patch.x,
		y: patch.y,
		width: patch.size,
		height: patch.size,
		rank: index + 1,
		label: `Region ${index + 1}`
	}));
}

export function presentRegions(patches: readonly PatchHit[]): PresentedRegion[] {
	return patches.map((patch, index) => ({
		id: String(patch.patch_id),
		label: `Region ${index + 1}`,
		slideId: patch.slide_id,
		thumbnailUrl: patch.thumbnail_url,
		score: presentRankScore(index),
		fly: regionFlyTarget(patch)
	}));
}

export function resultFooter(count: number, tookMs: number, kind: 'cases' | 'regions'): string {
	const noun =
		kind === 'cases' ? (count === 1 ? 'case' : 'cases') : count === 1 ? 'region' : 'regions';
	return `${count} ${noun} · ${tookMs} ms`;
}

export function classifySearchFailure(status: number, message: string): SearchFailure {
	const text = message.trim() || 'The search failed.';
	if (status === 422 && /no tissue/i.test(text)) return { kind: 'no-tissue', message: text };
	return { kind: 'error', message: text };
}

export function messageFromEnvelope(error: unknown): string {
	if (error && typeof error === 'object' && 'error' in error) {
		const body = (error as { error?: { message?: unknown } }).error;
		if (body && typeof body.message === 'string' && body.message.trim()) return body.message;
	}
	return 'The search failed.';
}

export function isSlideScopeResponse(
	data: SearchResponse | SlideScopeResponse
): data is SlideScopeResponse {
	return 'patches' in data && !('hits' in data);
}
