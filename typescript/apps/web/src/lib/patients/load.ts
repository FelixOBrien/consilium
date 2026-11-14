import { api } from '#lib/api/client.js';
import type { paths } from '#lib/api/schema.js';
import { PATIENT_PAGE_SIZE, PATIENT_SEARCH_LIMIT, type DirectoryQuery } from './query.js';
import type {
	PatchSearchRequest,
	PatientDetail,
	PatientSummary,
	ReportSearchRequest
} from './types.js';

type PatientListQuery = NonNullable<paths['/api/patients']['get']['parameters']['query']>;

export class PatientRequestError extends Error {
	readonly status: number;

	constructor(message: string, status: number) {
		super(message);
		this.name = 'PatientRequestError';
		this.status = status;
	}
}

export function isNotFound(error: unknown): boolean {
	return error instanceof PatientRequestError && error.status === 404;
}

export type PatientPage = {
	items: PatientSummary[];
	nextCursor: string | null;
};

/** Hit shape as the generated client returns it. */
export type PatientSearchResult = Awaited<ReturnType<typeof searchPatientReports>>;
export type CaseHit = PatientSearchResult['hits'][number];

export function toPatientListQuery(
	query: DirectoryQuery,
	cursor: string | null,
	limit = PATIENT_PAGE_SIZE
): PatientListQuery {
	const params: PatientListQuery = { limit };
	const q = query.q.trim();
	if (q) params.q = q;
	if (query.multiCase) params.multi_case = true;
	if (cursor) params.cursor = cursor;
	return params;
}

/** Keyword mode so highlighted passages work without a semantic encoder. */
export function reportSearchBody(patientId: string, text: string): ReportSearchRequest {
	return {
		text,
		mode: 'keyword',
		limit: PATIENT_SEARCH_LIMIT,
		filters: { patient_id: patientId }
	};
}

export function patchSearchBody(patientId: string, text: string): PatchSearchRequest {
	return {
		text,
		scope: 'corpus',
		limit: PATIENT_SEARCH_LIMIT,
		filters: { patient_id: patientId }
	};
}

export function appendPatients(
	current: PatientSummary[],
	page: PatientSummary[]
): PatientSummary[] {
	const seen = new Set(current.map((item) => item.id));
	const added = page.filter((item) => !seen.has(item.id));
	return added.length === 0 ? current : [...current, ...added];
}

export function errorMessage(error: unknown, fallback: string): string {
	if (error && typeof error === 'object' && 'error' in error) {
		const body = error.error;
		if (
			body &&
			typeof body === 'object' &&
			'message' in body &&
			typeof body.message === 'string' &&
			body.message.trim()
		) {
			return body.message;
		}
	}
	return fallback;
}

export async function fetchPatientPage(
	query: DirectoryQuery,
	cursor: string | null
): Promise<PatientPage> {
	const { data, error, response } = await api.GET('/api/patients', {
		params: { query: toPatientListQuery(query, cursor) }
	});
	if (!response.ok || !data) {
		throw new PatientRequestError(
			errorMessage(error, 'Patients could not be loaded.'),
			response.status
		);
	}
	return { items: data.items, nextCursor: data.next_cursor ?? null };
}

export async function fetchPatient(patientId: string): Promise<PatientDetail> {
	const { data, error, response } = await api.GET('/api/patients/{patient_id}', {
		params: { path: { patient_id: patientId } }
	});
	if (response.status === 404) {
		throw new PatientRequestError(errorMessage(error, 'Patient not found.'), 404);
	}
	if (!response.ok || !data) {
		throw new PatientRequestError(
			errorMessage(error, 'The patient record could not be loaded.'),
			response.status
		);
	}
	return data;
}

export async function searchPatientReports(patientId: string, text: string) {
	const { data, error, response } = await api.POST('/api/search/reports', {
		body: reportSearchBody(patientId, text)
	});
	if (!response.ok || !data) {
		throw new PatientRequestError(
			errorMessage(error, 'Report search could not run.'),
			response.status
		);
	}
	return { hits: data.hits, notice: data.notice ?? null };
}

export async function searchPatientTissue(
	patientId: string,
	text: string
): Promise<PatientSearchResult> {
	const { data, error, response } = await api.POST('/api/search/patches', {
		body: patchSearchBody(patientId, text)
	});
	if (!response.ok || !data || !('hits' in data)) {
		throw new PatientRequestError(
			errorMessage(error, 'Tissue search could not run.'),
			response.status
		);
	}
	return { hits: data.hits, notice: data.notice ?? null };
}
