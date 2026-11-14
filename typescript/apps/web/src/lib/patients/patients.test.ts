import { afterEach, describe, expect, test } from 'bun:test';
import {
	appendPatients,
	errorMessage,
	fetchPatient,
	isNotFound,
	patchSearchBody,
	PatientRequestError,
	reportSearchBody,
	toPatientListQuery
} from './load.js';
import {
	chronologicalCases,
	corpusSearchHref,
	highlightSegments,
	NOT_YET_REPORTED,
	pathologistSignedOutHref,
	presentDirectoryRow,
	presentPatient,
	presentSearchHits,
	presentTimeline,
	SIGNED_OUT,
	SINGLE_CASE_NOTE,
	visibleConclusion,
	visibleIcd10
} from './present.js';
import {
	directoryKey,
	parseDirectoryQuery,
	parsePatientSearch,
	writeDirectoryQuery,
	writePatientSearch,
	type DirectoryQuery
} from './query.js';
import { directoryScreen, patientRecordScreen, patientSearchScreen } from './screen.js';
import type { CaseHit } from './load.js';
import type { CaseSummary, PatientDetail, PatientSummary } from './types.js';

function summary(overrides: Partial<CaseSummary> = {}): CaseSummary {
	return {
		id: 'breast-FX-B042C',
		patient: {
			id: 'pt-0042',
			display_label: 'PT-0042',
			case_count: 3,
			is_synthetic_linkage: true,
			sex: 'F'
		},
		specimen_label: 'Recurrence excision',
		specialty: 'breast',
		patient_age: 61,
		patient_sex: 'F',
		icd10: 'C50.9',
		status: 'open',
		assigned_to: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		accessioned_at: '2026-11-02T09:00:00Z',
		slide_count: 1,
		thumbnail_url: '/api/slides/breast-FX-B042C-s1/thumbnail',
		conclusion_line: 'Synthetic fixture interpretation that must stay hidden.',
		...overrides
	};
}

function patient(overrides: Partial<PatientSummary> = {}): PatientSummary {
	return {
		id: 'pt-0042',
		display_label: 'PT-0042',
		sex: 'F',
		case_count: 3,
		is_synthetic_linkage: true,
		latest_accessioned_at: '2026-11-02T09:00:00Z',
		open_case_count: 1,
		signed_out_case_count: 2,
		specialties: ['breast'],
		...overrides
	};
}

function detail(cases: CaseSummary[], overrides: Partial<PatientDetail> = {}): PatientDetail {
	return {
		...patient(),
		birth_year: 1965,
		cases,
		...overrides
	};
}

function hit(overrides: Partial<CaseHit> = {}, caseOverrides: Partial<CaseSummary> = {}): CaseHit {
	return {
		author: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		case: summary({
			id: 'breast-FX-B042A',
			status: 'signed_out',
			conclusion_line: 'Signed conclusion.',
			...caseOverrides
		}),
		matched_by: ['keyword'],
		passage: {
			section: 'microscopic_description',
			text: 'Small calcifications sit beside the glands.',
			highlights: [[6, 20]]
		},
		patch_match_count: 0,
		patches: [],
		same_patient: true,
		score: 0.4,
		...overrides
	};
}

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
});

describe('patient directory URL', () => {
	test('round-trips search text and the multi-case filter', () => {
		const query: DirectoryQuery = { q: 'PT-0042', multiCase: true };
		const url = writeDirectoryQuery(new URL('http://localhost/patients?unrelated=1'), query);
		expect(url.searchParams.get('unrelated')).toBe('1');
		expect(parseDirectoryQuery(url.searchParams)).toEqual(query);
		expect(directoryKey(query)).toBe(directoryKey(parseDirectoryQuery(url.searchParams)));
	});

	test('drops an empty query and an off toggle', () => {
		const url = writeDirectoryQuery(new URL('http://localhost/patients?q=old&multi_case=true'), {
			q: '   ',
			multiCase: false
		});
		expect(url.search).toBe('');
		expect(parseDirectoryQuery(new URLSearchParams('multi_case=no'))).toEqual({
			q: '',
			multiCase: false
		});
	});

	test('list query sends q, multi_case and cursor only when set', () => {
		expect(toPatientListQuery({ q: ' pt ', multiCase: true }, 'pt-0007', 25)).toEqual({
			limit: 25,
			q: 'pt',
			multi_case: true,
			cursor: 'pt-0007'
		});
		expect(toPatientListQuery({ q: '', multiCase: false }, null)).toEqual({ limit: 50 });
	});
});

describe('patient search URL', () => {
	test('stores q and mode, and clears both when the query is empty', () => {
		const url = writePatientSearch(new URL('http://localhost/patients/pt-0042'), {
			q: 'calcifications',
			mode: 'tissue'
		});
		expect(parsePatientSearch(url.searchParams)).toEqual({
			q: 'calcifications',
			mode: 'tissue'
		});
		const cleared = writePatientSearch(url, { q: '', mode: 'tissue' });
		expect(cleared.search).toBe('');
		expect(parsePatientSearch(new URLSearchParams('mode=nope'))).toEqual({
			q: '',
			mode: 'reports'
		});
	});

	test('report and tissue requests are scoped to the patient', () => {
		expect(reportSearchBody('pt-0042', 'calcifications')).toEqual({
			text: 'calcifications',
			mode: 'keyword',
			limit: 20,
			filters: { patient_id: 'pt-0042' }
		});
		expect(patchSearchBody('pt-0042', 'glandular nests')).toEqual({
			text: 'glandular nests',
			scope: 'corpus',
			limit: 20,
			filters: { patient_id: 'pt-0042' }
		});
	});
});

describe('open-case withholding', () => {
	test('an open case hides conclusion and ICD-10 even when the payload includes them', () => {
		const open = summary();
		expect(visibleConclusion(open)).toBeNull();
		expect(visibleIcd10(open)).toBeNull();
		const [row] = presentTimeline(detail([open]));
		expect(row?.statusLabel).toBe(NOT_YET_REPORTED);
		expect(row?.conclusion).toBeNull();
		expect(row?.icd10).toBeNull();
		expect(row?.consultHref).toBe('/cases/breast-FX-B042C?panel=consult');
		expect(row?.pathologistRole).toBe('Assigned to');
		expect(row?.pathologistSynthetic).toBe(true);
	});

	test('a signed-out case shows the conclusion line and ICD-10', () => {
		const signed = summary({
			id: 'breast-FX-B042A',
			status: 'signed_out',
			specimen_label: 'Prior core biopsy',
			accessioned_at: '2025-08-04T09:00:00Z',
			conclusion_line: 'Invasive carcinoma of no special type.'
		});
		const [row] = presentTimeline(
			detail([signed], { case_count: 1, open_case_count: 0, signed_out_case_count: 1 })
		);
		expect(row?.statusLabel).toBe(SIGNED_OUT);
		expect(row?.conclusion).toBe('Invasive carcinoma of no special type.');
		expect(row?.icd10).toBe('C50.9');
		expect(row?.consultHref).toBeNull();
		expect(row?.pathologistRole).toBe('Reported by');
		expect(row?.accessioned).toBe('4 Aug 2025');
	});

	test('consult with history is only offered when an open case has signed-out history', () => {
		const open = summary();
		const alone = presentTimeline(
			detail([open], { case_count: 1, signed_out_case_count: 0, open_case_count: 1 })
		);
		expect(alone[0]?.consultHref).toBeNull();
	});

	test('search drops open cases, other patients, and report text from tissue mode', () => {
		const leaked = hit(
			{
				passage: {
					section: 'conclusion',
					text: 'SECRET OPEN CONCLUSION',
					highlights: [[0, 6]]
				}
			},
			{ id: 'breast-FX-B042C', status: 'open', conclusion_line: 'SECRET OPEN CONCLUSION' }
		);
		const other = hit({}, { id: 'skin-FX-S018A', status: 'signed_out' });
		other.case.patient = { ...other.case.patient, id: 'pt-0018', display_label: 'PT-0018' };
		const own = hit({
			patches: [
				{
					patch_id: 7,
					slide_id: 'breast-FX-B042A-s1',
					x: 10,
					y: 20,
					size: 512,
					similarity: 0.2,
					thumbnail_url: '/api/patches/7/thumbnail'
				},
				{
					patch_id: 8,
					slide_id: 'breast-FX-B042A-s1',
					x: 30,
					y: 40,
					size: 512,
					similarity: 0.1,
					thumbnail_url: '/api/patches/8/thumbnail'
				},
				{
					patch_id: 9,
					slide_id: 'breast-FX-B042A-s1',
					x: 50,
					y: 60,
					size: 512,
					similarity: 0.05,
					thumbnail_url: '/api/patches/9/thumbnail'
				},
				{
					patch_id: 10,
					slide_id: 'breast-FX-B042A-s1',
					x: 70,
					y: 80,
					size: 512,
					similarity: 0.01,
					thumbnail_url: '/api/patches/10/thumbnail'
				}
			]
		});
		const reports = presentSearchHits('pt-0042', 'reports', [leaked, other, own]);
		expect(reports.map((item) => item.caseId)).toEqual(['breast-FX-B042A']);
		expect(JSON.stringify(reports).includes('SECRET OPEN CONCLUSION')).toBe(false);
		expect(reports[0]?.passage?.sectionLabel).toBe('Microscopic description');
		expect(reports[0]?.passage?.segments).toEqual([
			{ text: 'Small ', highlighted: false },
			{ text: 'calcifications', highlighted: true },
			{ text: ' sit beside the glands.', highlighted: false }
		]);
		expect(reports[0]?.openHref).toBe('/cases/breast-FX-B042A');
		expect(reports[0]?.patches).toEqual([]);

		const tissue = presentSearchHits('pt-0042', 'tissue', [own]);
		expect(tissue[0]?.passage).toBeNull();
		expect(tissue[0]?.patches).toHaveLength(3);
		expect(tissue[0]?.openHref).toBe('/cases/breast-FX-B042A?patch=7');
		expect(tissue[0]?.peekPatch).toEqual({
			id: '7',
			slide_id: 'breast-FX-B042A-s1',
			x: 10,
			y: 20,
			size: 512
		});
		expect(tissue[0]?.icd10).toBe('C50.9');
	});
});

describe('timeline and header', () => {
	test('orders cases newest first and discloses synthetic linkage', () => {
		const older = summary({
			id: 'breast-FX-B042A',
			status: 'signed_out',
			accessioned_at: '2025-08-04T09:00:00Z',
			conclusion_line: 'Prior biopsy.'
		});
		const middle = summary({
			id: 'breast-FX-B042B',
			status: 'signed_out',
			accessioned_at: '2026-02-16T09:00:00Z',
			conclusion_line: 'Excision.'
		});
		const current = summary();
		const record = detail([older, current, middle]);
		expect(chronologicalCases(record.cases).map((item) => item.id)).toEqual([
			'breast-FX-B042C',
			'breast-FX-B042B',
			'breast-FX-B042A'
		]);
		const header = presentPatient(record);
		expect(header.syntheticLinkage).toBe(true);
		expect(header.birthYear).toBe('Approx. birth year 1965');
		expect(header.sex).toBe('Female');
		expect(header.openCount).toBe(1);
		expect(header.signedOutCount).toBe(2);
		expect(header.singleCase).toBe(false);
		expect(presentTimeline(record).map((item) => item.id)).toEqual([
			'breast-FX-B042C',
			'breast-FX-B042B',
			'breast-FX-B042A'
		]);
	});

	test('a single-case patient says no prior specimens are recorded', () => {
		const header = presentPatient(
			detail([summary({ status: 'signed_out' })], {
				case_count: 1,
				open_case_count: 0,
				signed_out_case_count: 1,
				is_synthetic_linkage: false
			})
		);
		expect(header.singleCase).toBe(true);
		expect(header.timelineNote).toBe(SINGLE_CASE_NOTE);
		expect(header.syntheticLinkage).toBe(false);
	});

	test('directory rows show counts and the synthetic linkage flag', () => {
		const row = presentDirectoryRow(patient());
		expect(row.displayLabel).toBe('PT-0042');
		expect(row.href).toBe('/patients/pt-0042');
		expect(row.sexSummary).toBe('Female');
		expect(row.caseCount).toBe(3);
		expect(row.openCount).toBe(1);
		expect(row.signedOutCount).toBe(2);
		expect(row.specialties).toBe('Breast');
		expect(row.syntheticLinkage).toBe(true);
		expect(row.latestAccessioned).toBe('2 Nov 2026');
		expect(pathologistSignedOutHref('path-okafor')).toBe(
			'/?view=all&status=signed_out&assigned_to=path-okafor'
		);
		expect(corpusSearchHref('calcifications', 'reports')).toBe(
			'/search?q=calcifications&mode=reports'
		);
	});

	test('highlight ranges merge and ignore inverted spans', () => {
		expect(
			highlightSegments('abcdef', [
				[4, 2],
				[1, 3],
				[2, 5]
			])
		).toEqual([
			{ text: 'a', highlighted: false },
			{ text: 'bcde', highlighted: true },
			{ text: 'f', highlighted: false }
		]);
	});
});

describe('screen states', () => {
	test('directory loading, error, empty filter, empty cohort and ready', () => {
		const query = { q: '', multiCase: false };
		expect(directoryScreen({ loading: true, failed: false, itemCount: 0, query }).kind).toBe(
			'loading'
		);
		expect(directoryScreen({ loading: false, failed: true, itemCount: 0, query }).kind).toBe(
			'error'
		);
		expect(
			directoryScreen({
				loading: false,
				failed: false,
				itemCount: 0,
				query: { q: 'zz', multiCase: false }
			}).kind
		).toBe('empty-filter');
		expect(
			directoryScreen({
				loading: false,
				failed: false,
				itemCount: 0,
				query: { q: '', multiCase: true }
			}).kind
		).toBe('empty-filter');
		expect(directoryScreen({ loading: false, failed: false, itemCount: 0, query }).kind).toBe(
			'empty'
		);
		expect(directoryScreen({ loading: false, failed: false, itemCount: 2, query }).kind).toBe(
			'ready'
		);
	});

	test('patient record and search states match S-09', () => {
		expect(patientRecordScreen({ loading: true, notFound: false, failed: false })).toBe('loading');
		expect(patientRecordScreen({ loading: false, notFound: true, failed: false })).toBe(
			'not-found'
		);
		expect(patientRecordScreen({ loading: false, notFound: false, failed: true })).toBe('error');
		expect(patientRecordScreen({ loading: false, notFound: false, failed: false })).toBe('ready');
		expect(patientSearchScreen({ active: false, loading: false, failed: false, hitCount: 0 })).toBe(
			'timeline'
		);
		expect(patientSearchScreen({ active: true, loading: true, failed: false, hitCount: 0 })).toBe(
			'loading'
		);
		expect(patientSearchScreen({ active: true, loading: false, failed: true, hitCount: 0 })).toBe(
			'error'
		);
		expect(patientSearchScreen({ active: true, loading: false, failed: false, hitCount: 0 })).toBe(
			'empty'
		);
		expect(patientSearchScreen({ active: true, loading: false, failed: false, hitCount: 2 })).toBe(
			'results'
		);
	});
});

describe('patient requests', () => {
	test('appends a page without duplicating ids', () => {
		const first = patient();
		const second = patient({ id: 'pt-0007', display_label: 'PT-0007' });
		expect(appendPatients([first], [first, second]).map((item) => item.id)).toEqual([
			'pt-0042',
			'pt-0007'
		]);
	});

	test('maps a 404 envelope to not found', async () => {
		globalThis.fetch = async () =>
			new Response(
				JSON.stringify({ error: { code: 'not_found', message: 'Patient not found.' } }),
				{ status: 404, headers: { 'content-type': 'application/json' } }
			);
		const error = await fetchPatient('pt-missing').catch((caught: unknown) => caught);
		expect(isNotFound(error)).toBe(true);
		expect(error instanceof PatientRequestError).toBe(true);
		expect(errorMessage({ error: { message: 'Patient not found.' } }, 'fallback')).toBe(
			'Patient not found.'
		);
	});
});
