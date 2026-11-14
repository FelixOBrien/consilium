import { api } from '#lib/api/client.js';
import { appendCases } from './present.js';
import {
	emptyWorklistQuery,
	toCaseQuery,
	WORKLIST_PAGE_SIZE,
	type CaseSummary,
	type WorklistQuery,
	type WorklistView
} from './query.js';

export type CasePage = {
	items: CaseSummary[];
	next_cursor?: string | null;
};

export interface CaseSource {
	list(query: WorklistQuery, cursor: string | null, limit: number): Promise<CasePage>;
}

export type ViewTally = {
	total: number;
	open: number;
	truncated: boolean;
};

export type WorklistTallies = {
	mine: ViewTally;
	all: ViewTally;
};

const TALLY_PAGE_SIZE = 100;
const TALLY_PAGE_CAP = 20;

const tallyCache = new Map<string, Promise<WorklistTallies>>();

export function clearWorklistTallies(): void {
	tallyCache.clear();
}

export function apiCaseSource(): CaseSource {
	return {
		list(query, cursor, limit) {
			return fetchCasePage(query, cursor, limit);
		}
	};
}

export async function fetchCasePage(
	query: WorklistQuery,
	cursor: string | null,
	limit = WORKLIST_PAGE_SIZE
): Promise<CasePage> {
	const { data, error, response } = await api.GET('/api/cases', {
		params: { query: toCaseQuery(query, cursor, limit) }
	});
	if (!response.ok || !data) {
		throw new Error(caseErrorMessage(error, response.status));
	}
	return { items: data.items, next_cursor: data.next_cursor };
}

export async function tallyView(
	source: CaseSource,
	view: WorklistView,
	maxPages = TALLY_PAGE_CAP
): Promise<ViewTally> {
	let total = 0;
	let open = 0;
	let cursor: string | null = null;
	const query = { ...emptyWorklistQuery(), view };
	for (let page = 0; page < maxPages; page += 1) {
		const result = await source.list(query, cursor, TALLY_PAGE_SIZE);
		total += result.items.length;
		open += result.items.filter((item) => item.status === 'open').length;
		const next = result.next_cursor ?? null;
		if (!next) return { total, open, truncated: false };
		cursor = next;
	}
	return { total, open, truncated: true };
}

export async function computeWorklistTallies(source: CaseSource): Promise<WorklistTallies> {
	const [mine, all] = await Promise.all([tallyView(source, 'mine'), tallyView(source, 'all')]);
	return { mine, all };
}

/** Unfiltered view sizes for the switch. Cached per acting pathologist. */
export function worklistTallies(userId: string, source: CaseSource): Promise<WorklistTallies> {
	const cached = tallyCache.get(userId);
	if (cached) return cached;
	const pending = computeWorklistTallies(source).catch((error: unknown) => {
		tallyCache.delete(userId);
		throw error;
	});
	tallyCache.set(userId, pending);
	return pending;
}

function caseErrorMessage(error: unknown, status: number): string {
	if (error && typeof error === 'object' && 'error' in error) {
		const body = error.error;
		if (body && typeof body === 'object' && 'message' in body && typeof body.message === 'string') {
			return body.message;
		}
	}
	return `The worklist could not be loaded (${status}).`;
}

export function formatTally(tally: ViewTally | undefined): string | undefined {
	if (!tally) return undefined;
	return tally.truncated ? `${tally.total}+` : String(tally.total);
}

export async function loadFirstPage(
	source: CaseSource,
	query: WorklistQuery
): Promise<{ items: CaseSummary[]; nextCursor: string | null }> {
	const page = await source.list(query, null, WORKLIST_PAGE_SIZE);
	return { items: page.items, nextCursor: page.next_cursor ?? null };
}

export async function loadNextPage(
	source: CaseSource,
	query: WorklistQuery,
	cursor: string,
	current: CaseSummary[]
): Promise<{ items: CaseSummary[]; nextCursor: string | null }> {
	const page = await source.list(query, cursor, WORKLIST_PAGE_SIZE);
	return {
		items: appendCases(current, page.items),
		nextCursor: page.next_cursor ?? null
	};
}
