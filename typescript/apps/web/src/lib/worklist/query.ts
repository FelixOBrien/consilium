import type { paths } from '#lib/api/schema.js';

export type CaseSummary = import('#lib/api/schema.js').components['schemas']['CaseSummary'];
export type CaseStatus = import('#lib/api/schema.js').components['schemas']['CaseStatus'];
export type Specialty = import('#lib/api/schema.js').components['schemas']['Specialty'];
export type Pathologist = import('#lib/api/schema.js').components['schemas']['Pathologist'];

export type WorklistView = 'mine' | 'all';

/** Filters that live in the worklist URL (screens index, F-01.5). */
export type WorklistQuery = {
	view: WorklistView;
	status: CaseStatus | null;
	specialty: Specialty | null;
	assignedTo: string | null;
	icd10: string | null;
	patientId: string | null;
};

export const WORKLIST_PAGE_SIZE = 50;

export const SPECIALTIES = [
	'breast',
	'thorax',
	'colorectal',
	'gastrointestinal',
	'hematologic',
	'skin'
] as const satisfies readonly Specialty[];

export const CASE_STATUSES = ['open', 'signed_out'] as const satisfies readonly CaseStatus[];

const SPECIALTY_LABEL: Record<Specialty, string> = {
	breast: 'Breast',
	thorax: 'Thoracic',
	colorectal: 'Colorectal',
	gastrointestinal: 'Gastrointestinal',
	hematologic: 'Hematologic',
	skin: 'Skin'
};

const STATUS_LABEL: Record<CaseStatus, string> = {
	open: 'Open',
	signed_out: 'Signed out'
};

type CaseListQuery = NonNullable<paths['/api/cases']['get']['parameters']['query']>;

export function specialtyLabel(specialty: Specialty): string {
	return SPECIALTY_LABEL[specialty];
}

export function statusLabel(status: CaseStatus): string {
	return STATUS_LABEL[status];
}

export function emptyWorklistQuery(): WorklistQuery {
	return {
		view: 'mine',
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

/** Read view and filters from the URL. Unknown values are dropped. My cases is the default. */
export function parseWorklistQuery(params: { get(name: string): string | null }): WorklistQuery {
	const view = params.get('view') === 'all' ? 'all' : 'mine';
	const status = params.get('status');
	const specialty = params.get('specialty');
	const icd10 = nonempty(params.get('icd10'))?.toUpperCase() ?? null;
	return {
		view,
		status: isStatus(status) ? status : null,
		specialty: isSpecialty(specialty) ? specialty : null,
		assignedTo: nonempty(params.get('assigned_to')),
		icd10,
		patientId: nonempty(params.get('patient_id'))
	};
}

export function hasWorklistFilters(query: WorklistQuery): boolean {
	return Boolean(
		query.status || query.specialty || query.assignedTo || query.icd10 || query.patientId
	);
}

/** Drop every filter and keep the current view. */
export function clearedFilters(query: WorklistQuery): WorklistQuery {
	return { ...emptyWorklistQuery(), view: query.view };
}

function setParam(params: URLSearchParams, key: string, value: string | null): void {
	if (value) params.set(key, value);
	else params.delete(key);
}

/** Write the worklist query onto a URL, replacing any previous worklist params. */
export function writeWorklistQuery(url: URL, query: WorklistQuery): URL {
	const next = new URL(url.href);
	setParam(next.searchParams, 'view', query.view);
	setParam(next.searchParams, 'status', query.status);
	setParam(next.searchParams, 'specialty', query.specialty);
	setParam(next.searchParams, 'assigned_to', query.assignedTo);
	setParam(next.searchParams, 'icd10', query.icd10);
	setParam(next.searchParams, 'patient_id', query.patientId);
	return next;
}

export function worklistQueryKey(query: WorklistQuery): string {
	return writeWorklistQuery(new URL('http://worklist.local/'), query).search;
}

export function toCaseQuery(
	query: WorklistQuery,
	cursor: string | null,
	limit = WORKLIST_PAGE_SIZE
): CaseListQuery {
	const params: CaseListQuery = { view: query.view, limit };
	if (query.status) params.status = query.status;
	if (query.specialty) params.specialty = query.specialty;
	if (query.assignedTo) params.assigned_to = query.assignedTo;
	if (query.icd10) params.icd10 = query.icd10;
	if (query.patientId) params.patient_id = query.patientId;
	if (cursor) params.cursor = cursor;
	return params;
}
