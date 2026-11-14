import { api } from '#lib/api/client.js';
import { exactKind, mergeCaseLookups, redactSummary, toCaseSummary } from './present.js';
import {
	caseMatchesFilters,
	looksLikeIdentifier,
	matchesPathologist,
	toPatchRequest,
	toReportRequest,
	type CaseHit,
	type CaseSummary,
	type SearchQuery
} from './query.js';

type SearchResponse = import('#lib/api/schema.js').components['schemas']['SearchResponse'];

export type SearchOutcome = {
	hits: CaseHit[];
	tookMs: number;
	notice: string | null;
	totalCandidates: number;
};

const LOOKUP_PAGE_CAP = 4;
const LOOKUP_PAGE_SIZE = 100;

export function searchErrorMessage(error: unknown, status: number): string {
	if (isEnvelope(error)) return error.error.message;
	if (status === 422) return 'That query could not be searched.';
	return 'Search failed. The query and filters are unchanged.';
}

function isEnvelope(error: unknown): error is { error: { message: string } } {
	if (!error || typeof error !== 'object' || !('error' in error)) return false;
	const body = (error as { error?: { message?: unknown } }).error;
	return typeof body?.message === 'string' && body.message.trim() !== '';
}

async function postReports(query: SearchQuery): Promise<SearchResponse> {
	const { data, error, response } = await api.POST('/api/search/reports', {
		body: toReportRequest(query)
	});
	if (!response.ok || !data) throw new Error(searchErrorMessage(error, response.status));
	// openapi-fetch widens highlight pairs to number[][]; the schema type is the contract.
	return data as unknown as SearchResponse;
}

async function postPatches(query: SearchQuery): Promise<SearchResponse> {
	const { data, error, response } = await api.POST('/api/search/patches', {
		body: toPatchRequest(query)
	});
	if (!response.ok || !data) throw new Error(searchErrorMessage(error, response.status));
	if (!('hits' in data)) throw new Error('Search did not return cases.');
	return data as unknown as SearchResponse;
}

/**
 * Exact and partial case ids are not always in the hybrid ranking (an open case
 * has no report text). `GET /api/cases` supplies those rows; report text still
 * comes only from search, and open rows are redacted before display.
 */
export async function lookupCases(query: SearchQuery): Promise<CaseSummary[]> {
	if (query.mode !== 'reports' || !looksLikeIdentifier(query.q)) return [];
	const found = new Map<string, CaseSummary>();
	const needle = query.q.trim();
	const direct = await api.GET('/api/cases/{case_id}', {
		params: { path: { case_id: needle } }
	});
	if (direct.data) {
		const summary = toCaseSummary(direct.data);
		if (caseMatchesFilters(summary, query) && exactKind(query.q, summary)) {
			found.set(summary.id.toLowerCase(), summary);
		}
	}

	let cursor: string | undefined;
	for (let page = 0; page < LOOKUP_PAGE_CAP; page += 1) {
		const listed = await api.GET('/api/cases', {
			params: {
				query: {
					view: 'all',
					limit: LOOKUP_PAGE_SIZE,
					status: query.status ?? undefined,
					specialty: query.specialty ?? undefined,
					assigned_to: query.assignedTo ?? undefined,
					icd10: query.icd10 ?? undefined,
					patient_id: query.patientId ?? undefined,
					cursor
				}
			}
		});
		if (!listed.response.ok || !listed.data) break;
		for (const item of listed.data.items) {
			const summary = redactSummary(item);
			if (!exactKind(query.q, summary)) continue;
			found.set(summary.id.toLowerCase(), summary);
		}
		const next = listed.data.next_cursor ?? null;
		if (!next) break;
		cursor = next;
	}
	return [...found.values()];
}

export async function runSearch(query: SearchQuery): Promise<SearchOutcome> {
	const [response, lookedUp] = await Promise.all([
		query.mode === 'tissue' ? postPatches(query) : postReports(query),
		lookupCases(query).catch(() => [] as CaseSummary[])
	]);
	const hits = mergeCaseLookups(response.hits, lookedUp, query).filter((hit) =>
		matchesPathologist(hit, query.assignedTo)
	);
	return {
		hits,
		tookMs: response.took_ms,
		notice: response.notice ?? null,
		totalCandidates: response.total_candidates
	};
}
