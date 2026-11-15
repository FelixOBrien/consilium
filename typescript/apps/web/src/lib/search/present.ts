import type { CasePeekPatch } from '#lib/case-peek.svelte.js';
import type { components } from '#lib/api/schema.js';
import { formatAgeSex } from '#lib/worklist/present.js';
import { specialtyLabel } from '#lib/worklist/query.js';
import {
	caseMatchesFilters,
	looksLikeIdentifier,
	type CaseHit,
	type CaseSummary,
	type SearchQuery
} from './query.js';

export type PatchHit = components['schemas']['PatchHit'];
export type CaseDetail = components['schemas']['CaseDetail'];

/** Why a hit was pulled ahead of ranked retrieval (F-02.3). */
export type ExactKind = 'case' | 'patient' | 'icd10' | 'case-prefix';

export type MatchLabel = 'Keyword' | 'Meaning' | 'Both';

export type TextSegment = {
	text: string;
	mark: boolean;
};

export type PresentedPassage = {
	sectionLabel: string;
	text: string;
	highlights: [number, number][];
};

/** View model. Open cases never carry report text, a conclusion or an ICD-10 code. */
export type PresentedHit = {
	id: string;
	patientId: string;
	patientLabel: string;
	patientCaseCount: number;
	specialtyLabel: string;
	ageSex: string;
	status: CaseSummary['status'];
	open: boolean;
	icd10: string | null;
	authorName: string;
	authorId: string;
	authorSynthetic: boolean;
	score: number;
	matchLabel: MatchLabel | null;
	passage: PresentedPassage | null;
	patches: PatchHit[];
	patchCount: number;
	conclusion: string | null;
	exact: ExactKind | null;
};

const SECTION_LABEL: Record<string, string> = {
	clinical_history: 'Clinical history',
	gross_description: 'Gross description',
	microscopic_description: 'Microscopic description',
	conclusion: 'Conclusion',
	additional_info: 'Additional information',
	body: 'Report'
};

const EXACT_RANK: Record<ExactKind, number> = {
	case: 0,
	patient: 1,
	icd10: 2,
	'case-prefix': 3
};

/** CSS pixels the opened patch should occupy. URL `zoom` is CSS pixels per level-0 pixel. */
const PATCH_FOCUS_CSS = 320;

export function sectionLabel(section: string): string {
	return SECTION_LABEL[section] ?? 'Report';
}

export function exactBadge(kind: ExactKind | null): string | null {
	switch (kind) {
		case 'case':
			return 'Exact case';
		case 'patient':
			return 'Exact patient';
		case 'icd10':
			return 'Exact ICD-10';
		case 'case-prefix':
			return 'Partial case ID';
		default:
			return null;
	}
}

export function matchLabel(matchedBy: readonly string[]): MatchLabel | null {
	const keyword = matchedBy.includes('keyword');
	const semantic = matchedBy.includes('semantic');
	if (keyword && semantic) return 'Both';
	if (keyword) return 'Keyword';
	if (semantic) return 'Meaning';
	return null;
}

/**
 * Open cases can be returned for an exact case id. Drop anything that would
 * show a report, a conclusion or an ICD-10 code (S-07, F-02).
 */
export function redactSummary(summary: CaseSummary): CaseSummary {
	if (summary.status !== 'open') return summary;
	if (summary.icd10 == null && !summary.conclusion_line) return summary;
	return { ...summary, icd10: null, conclusion_line: null };
}

export function redactHit(hit: CaseHit): CaseHit {
	const summary = redactSummary(hit.case);
	if (summary.status !== 'open') return summary === hit.case ? hit : { ...hit, case: summary };
	return { ...hit, case: summary, passage: null };
}

export function toCaseSummary(detail: CaseDetail): CaseSummary {
	return redactSummary({
		id: detail.id,
		accessioned_at: detail.accessioned_at,
		assigned_to: detail.assigned_to,
		conclusion_line: detail.conclusion_line ?? null,
		icd10: detail.icd10,
		patient: detail.patient,
		patient_age: detail.patient_age,
		patient_sex: detail.patient_sex,
		slide_count: detail.slide_count,
		specialty: detail.specialty,
		specimen_label: detail.specimen_label,
		status: detail.status,
		thumbnail_url: detail.thumbnail_url
	});
}

export function exactKind(query: string, summary: CaseSummary): ExactKind | null {
	const needle = query.trim().toLowerCase();
	if (!needle) return null;
	const id = summary.id.toLowerCase();
	if (id === needle) return 'case';
	const patientId = summary.patient.id.toLowerCase();
	const label = summary.patient.display_label.toLowerCase();
	if (patientId === needle || label === needle) return 'patient';
	const code = summary.icd10?.trim().toLowerCase() ?? '';
	if (code && code === needle) return 'icd10';
	if (looksLikeIdentifier(query) && (id.startsWith(needle) || id.includes(needle))) {
		return 'case-prefix';
	}
	return null;
}

function exactRank(kind: ExactKind | null): number {
	return kind == null ? 4 : EXACT_RANK[kind];
}

export function sortHits(hits: readonly CaseHit[], query: string): CaseHit[] {
	return hits
		.map((hit, index) => ({ hit, index, rank: exactRank(exactKind(query, hit.case)) }))
		.sort((a, b) => a.rank - b.rank || a.index - b.index)
		.map((item) => item.hit);
}

export function summaryToHit(summary: CaseSummary): CaseHit {
	const safe = redactSummary(summary);
	return {
		case: safe,
		author: safe.assigned_to,
		same_patient: false,
		score: 1,
		matched_by: [],
		patches: [],
		patch_match_count: 0,
		passage: null
	};
}

/** Prepend case-list matches the report search did not already return, then order exact hits first. */
export function mergeCaseLookups(
	hits: readonly CaseHit[],
	extra: readonly CaseSummary[],
	query: SearchQuery
): CaseHit[] {
	const merged = hits.map((hit) => redactHit(hit));
	const seen = new Set(merged.map((hit) => hit.case.id.toLowerCase()));
	for (const summary of extra) {
		const safe = redactSummary(summary);
		if (!caseMatchesFilters(safe, query)) continue;
		if (!exactKind(query.q, safe)) continue;
		const key = safe.id.toLowerCase();
		if (seen.has(key)) continue;
		seen.add(key);
		merged.push(summaryToHit(safe));
	}
	return sortHits(merged, query.q);
}

export function highlightSegments(
	text: string,
	ranges: readonly (readonly [number, number])[]
): TextSegment[] {
	if (!text) return [];
	const spans: [number, number][] = [];
	for (const range of ranges) {
		if (range.length < 2) continue;
		const start = clampOffset(range[0], text.length);
		const end = clampOffset(range[1], text.length);
		if (end <= start) continue;
		spans.push([start, end]);
	}
	spans.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
	const merged: [number, number][] = [];
	for (const [start, end] of spans) {
		const last = merged.at(-1);
		if (last && start <= last[1]) last[1] = Math.max(last[1], end);
		else merged.push([start, end]);
	}
	const segments: TextSegment[] = [];
	let cursor = 0;
	for (const [start, end] of merged) {
		if (start > cursor) segments.push({ text: text.slice(cursor, start), mark: false });
		segments.push({ text: text.slice(start, end), mark: true });
		cursor = end;
	}
	if (cursor < text.length) segments.push({ text: text.slice(cursor), mark: false });
	return segments;
}

function clampOffset(value: number, length: number): number {
	if (!Number.isFinite(value)) return 0;
	return Math.max(0, Math.min(length, Math.trunc(value)));
}

function firstLine(value: string | null | undefined): string | null {
	if (!value) return null;
	const line = value
		.split('\n')
		.map((part) => part.trim())
		.find(Boolean);
	return line || null;
}

function clampScore(score: number): number {
	if (!Number.isFinite(score)) return 0;
	return Math.min(1, Math.max(0, score));
}

export function presentHit(hit: CaseHit, query: string): PresentedHit {
	const safe = redactHit(hit);
	const summary = safe.case;
	const open = summary.status === 'open';
	const passage = open || !safe.passage ? null : safe.passage;
	return {
		id: summary.id,
		patientId: summary.patient.id,
		patientLabel: summary.patient.display_label,
		patientCaseCount: summary.patient.case_count,
		specialtyLabel: specialtyLabel(summary.specialty),
		ageSex: formatAgeSex(summary.patient_age, summary.patient_sex),
		status: summary.status,
		open,
		icd10: open ? null : (summary.icd10 ?? null),
		authorName: safe.author.name,
		authorId: safe.author.id,
		authorSynthetic: safe.author.is_synthetic,
		score: clampScore(safe.score),
		matchLabel: matchLabel(safe.matched_by),
		passage: passage
			? {
					sectionLabel: sectionLabel(passage.section),
					text: passage.text,
					highlights: passage.highlights.map((range): [number, number] => [range[0], range[1]])
				}
			: null,
		patches: safe.patches.slice(0, 3),
		patchCount: safe.patch_match_count,
		conclusion: open ? null : firstLine(summary.conclusion_line),
		exact: exactKind(query, summary)
	};
}

export function patchThumbnail(patch: PatchHit): string {
	const url = patch.thumbnail_url.trim();
	return url || `/api/patches/${patch.patch_id}/thumbnail`;
}

export function peekTarget(patch: PatchHit): CasePeekPatch {
	return {
		id: String(patch.patch_id),
		slide_id: patch.slide_id,
		x: patch.x,
		y: patch.y,
		size: patch.size
	};
}

/** Zoom that shows `size` level-0 pixels across about 320 CSS pixels. */
export function patchZoom(size: number): string {
	if (!Number.isFinite(size) || size <= 0) return '1';
	return String(Number((PATCH_FOCUS_CSS / size).toPrecision(6)));
}

/**
 * Reports open on the report panel. A tissue hit opens centred on the patch:
 * level-0 centre in `x`/`y`, CSS-pixels-per-level-0-pixel in `zoom`, and `patch`
 * so the viewer can outline that patch.
 */
export function openHref(
	caseId: string,
	mode: 'reports' | 'tissue',
	patch: PatchHit | null
): string {
	const path = `/cases/${encodeURIComponent(caseId)}`;
	if (mode !== 'tissue' || !patch) return `${path}?panel=report`;
	const params = new URLSearchParams({
		slide: patch.slide_id,
		x: String(Math.round(patch.x + patch.size / 2)),
		y: String(Math.round(patch.y + patch.size / 2)),
		zoom: patchZoom(patch.size),
		patch: String(patch.patch_id)
	});
	return `${path}?${params.toString()}`;
}

export function resultSummary(count: number, tookMs: number): string {
	const cases = count === 1 ? '1 case' : `${count} cases`;
	return `${cases} · ${tookMs} ms server time`;
}
