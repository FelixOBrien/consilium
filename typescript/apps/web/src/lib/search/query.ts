import type { components } from '#lib/api/schema.js';
import { SPECIALTIES, type CaseStatus, type Specialty } from '#lib/worklist/query.js';

export type SearchMode = 'reports' | 'tissue';

/** Filters that live in the search URL (S-07, screens index). */
export type SearchQuery = {
	q: string;
	mode: SearchMode;
	status: CaseStatus | null;
	specialty: Specialty | null;
	assignedTo: string | null;
	icd10: string | null;
	patientId: string | null;
};

export type CaseSummary = components['schemas']['CaseSummary'];
export type CaseHit = components['schemas']['CaseHit'];
export type SearchFilters = components['schemas']['SearchFilters'];
export type ReportSearchRequest = components['schemas']['ReportSearchRequest'];
export type PatchSearchRequest = components['schemas']['PatchSearchRequest'];

export const SEARCH_LIMIT = 20;

export function emptySearchQuery(): SearchQuery {
	return {
		q: '',
		mode: 'reports',
		status: null,
		specialty: null,
		assignedTo: null,
		icd10: null,
		patientId: null
	};
}

function nonempty(value: string | null): string | null {
	const trimmed = value?.trim() ?? '';
	return trimmed || null;
}

function isStatus(value: string | null): value is CaseStatus {
	return value === 'open' || value === 'signed_out';
}

function isSpecialty(value: string | null): value is Specialty {
	return SPECIALTIES.some((specialty) => specialty === value);
}

function isMode(value: string | null): value is SearchMode {
	return value === 'reports' || value === 'tissue';
}

/**
 * A case id, patient label or code, rather than report prose.
 * Used to decide when a direct case lookup is worth doing.
 */
export function looksLikeIdentifier(text: string): boolean {
	const query = text.trim();
	if (query.length < 4 || /\s/.test(query)) return false;
	return /[0-9]/.test(query) || query.includes('-');
}

/** Read the search screen from the URL. Unknown filter values are dropped. */
export function parseSearchQuery(params: { get(name: string): string | null }): SearchQuery {
	const mode = params.get('mode');
	const status = params.get('status');
	const specialty = params.get('specialty');
	return {
		q: params.get('q')?.trim() ?? '',
		mode: isMode(mode) ? mode : 'reports',
		status: isStatus(status) ? status : null,
		specialty: isSpecialty(specialty) ? specialty : null,
		assignedTo: nonempty(params.get('assigned_to')) ?? nonempty(params.get('pathologist_id')),
		icd10: nonempty(params.get('icd10'))?.toUpperCase() ?? null,
		patientId: nonempty(params.get('patient_id'))
	};
}

export function hasSearchFilters(query: SearchQuery): boolean {
	return Boolean(
		query.status || query.specialty || query.assignedTo || query.icd10 || query.patientId
	);
}

function setParam(params: URLSearchParams, key: string, value: string | null): void {
	if (value) params.set(key, value);
	else params.delete(key);
}

/** Write the search query onto a URL. `assigned_to` is the canonical pathologist param. */
export function writeSearchQuery(url: URL, query: SearchQuery): URL {
	const next = new URL(url.href);
	setParam(next.searchParams, 'q', query.q.trim() || null);
	setParam(next.searchParams, 'mode', query.mode);
	setParam(next.searchParams, 'status', query.status);
	setParam(next.searchParams, 'specialty', query.specialty);
	setParam(next.searchParams, 'assigned_to', query.assignedTo);
	next.searchParams.delete('pathologist_id');
	setParam(next.searchParams, 'icd10', query.icd10 ? query.icd10.toUpperCase() : null);
	setParam(next.searchParams, 'patient_id', query.patientId);
	return next;
}

/** Path for this search, or `/` when the query is empty (F-02.9). */
export function searchHref(query: SearchQuery): string {
	if (!query.q.trim()) return '/';
	const url = writeSearchQuery(new URL('http://search.local/search'), query);
	return `${url.pathname}${url.search}`;
}

export function searchQueryKey(query: SearchQuery): string {
	return searchHref(query);
}

/** Global search box: a fresh reports search, with no leftover filters. */
export function globalSearchHref(text: string): string {
	return searchHref({ ...emptySearchQuery(), q: text, mode: 'reports' });
}

export function toSearchFilters(query: SearchQuery): SearchFilters | undefined {
	const filters: SearchFilters = {};
	if (query.status) filters.status = query.status;
	if (query.specialty) filters.specialty = [query.specialty];
	if (query.icd10) filters.icd10_prefix = query.icd10;
	if (query.patientId) filters.patient_id = query.patientId;
	if (!filters.status && !filters.specialty && !filters.icd10_prefix && !filters.patient_id) {
		return undefined;
	}
	return filters;
}

/** Hybrid report search. No `context_case_id`: this is corpus search, not evidence search. */
export function toReportRequest(query: SearchQuery): ReportSearchRequest {
	const body: ReportSearchRequest = {
		text: query.q.trim(),
		mode: 'hybrid',
		limit: SEARCH_LIMIT
	};
	const filters = toSearchFilters(query);
	if (filters) body.filters = filters;
	return body;
}

/** Text-to-patch search over the corpus. No `context_case_id`. */
export function toPatchRequest(query: SearchQuery): PatchSearchRequest {
	const body: PatchSearchRequest = {
		text: query.q.trim(),
		scope: 'corpus',
		limit: SEARCH_LIMIT
	};
	const filters = toSearchFilters(query);
	if (filters) body.filters = filters;
	return body;
}

export function caseMatchesFilters(summary: CaseSummary, query: SearchQuery): boolean {
	if (query.status && summary.status !== query.status) return false;
	if (query.specialty && summary.specialty !== query.specialty) return false;
	if (query.patientId && summary.patient.id !== query.patientId) return false;
	if (query.assignedTo && summary.assigned_to.id !== query.assignedTo) return false;
	if (query.icd10) {
		const code = summary.icd10?.toUpperCase() ?? '';
		if (!code.startsWith(query.icd10.toUpperCase())) return false;
	}
	return true;
}

/** The search API has no pathologist filter, so this is applied to the returned hits. */
export function matchesPathologist(hit: CaseHit, assignedTo: string | null): boolean {
	if (!assignedTo) return true;
	return hit.author.id === assignedTo || hit.case.assigned_to.id === assignedTo;
}
