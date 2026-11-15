import type { PatientSearchMode } from './types.js';

/** Directory filters stored in the `/patients` URL. */
export type DirectoryQuery = {
	q: string;
	multiCase: boolean;
};

/** Patient-scoped search stored on S-09 (`q`, `mode`). */
export type PatientSearchQuery = {
	q: string;
	mode: PatientSearchMode;
};

export const PATIENT_PAGE_SIZE = 50;
export const PATIENT_SEARCH_LIMIT = 20;

export function emptyDirectoryQuery(): DirectoryQuery {
	return { q: '', multiCase: false };
}

export function parseDirectoryQuery(params: { get(name: string): string | null }): DirectoryQuery {
	const multi = params.get('multi_case');
	return {
		q: params.get('q')?.trim() ?? '',
		multiCase: multi === 'true' || multi === '1'
	};
}

export function writeDirectoryQuery(url: URL, query: DirectoryQuery): URL {
	const next = new URL(url.href);
	const q = query.q.trim();
	if (q) next.searchParams.set('q', q);
	else next.searchParams.delete('q');
	if (query.multiCase) next.searchParams.set('multi_case', 'true');
	else next.searchParams.delete('multi_case');
	return next;
}

export function directoryKey(query: DirectoryQuery): string {
	return `${query.multiCase ? '1' : '0'}\n${query.q.trim()}`;
}

export function hasDirectoryFilter(query: DirectoryQuery): boolean {
	return Boolean(query.q.trim() || query.multiCase);
}

export function parsePatientSearch(params: {
	get(name: string): string | null;
}): PatientSearchQuery {
	return {
		q: params.get('q')?.trim() ?? '',
		mode: params.get('mode') === 'tissue' ? 'tissue' : 'reports'
	};
}

/** An empty query drops `q` and `mode` so the timeline URL is clean. */
export function writePatientSearch(url: URL, query: PatientSearchQuery): URL {
	const next = new URL(url.href);
	const q = query.q.trim();
	if (!q) {
		next.searchParams.delete('q');
		next.searchParams.delete('mode');
		return next;
	}
	next.searchParams.set('q', q);
	next.searchParams.set('mode', query.mode === 'tissue' ? 'tissue' : 'reports');
	return next;
}
