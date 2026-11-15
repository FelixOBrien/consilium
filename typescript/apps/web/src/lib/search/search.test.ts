import { describe, expect, test } from 'bun:test';
import { searchErrorMessage } from './load.js';
import {
	exactBadge,
	exactKind,
	highlightSegments,
	matchLabel,
	mergeCaseLookups,
	openHref,
	patchThumbnail,
	patchZoom,
	presentHit,
	redactSummary,
	resultSummary,
	type PatchHit
} from './present.js';
import { searchScreen } from './screen.js';
import {
	emptySearchQuery,
	globalSearchHref,
	parseSearchQuery,
	searchHref,
	toPatchRequest,
	toReportRequest,
	writeSearchQuery,
	type CaseHit,
	type CaseSummary,
	type SearchQuery
} from './query.js';

function summary(overrides: Partial<CaseSummary> = {}): CaseSummary {
	return {
		id: 'breast-FX-B042A',
		patient: {
			id: 'pt-0042',
			display_label: 'PT-0042',
			case_count: 3,
			is_synthetic_linkage: true,
			sex: 'F'
		},
		specimen_label: 'Excision',
		specialty: 'breast',
		patient_age: 61,
		patient_sex: 'F',
		icd10: 'C50.9',
		status: 'signed_out',
		assigned_to: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		accessioned_at: '2026-11-01T00:00:00Z',
		slide_count: 1,
		thumbnail_url: '/api/slides/breast-FX-B042A-s1/thumbnail',
		conclusion_line: 'Invasive carcinoma of no special type.',
		...overrides
	};
}

function hit(
	overrides: Partial<Omit<CaseHit, 'case'>> = {},
	caseOverrides: Partial<CaseSummary> = {}
): CaseHit {
	const item = summary(caseOverrides);
	return {
		case: item,
		author: item.assigned_to,
		same_patient: false,
		score: 0.4,
		matched_by: ['keyword'],
		patches: [],
		patch_match_count: 0,
		passage: {
			section: 'microscopic_description',
			text: 'Small calcifications sit beside the glands.',
			highlights: [[6, 19]]
		},
		...overrides
	};
}

const patch: PatchHit = {
	patch_id: 42,
	slide_id: 'breast-FX-B042A-s1',
	x: 1000,
	y: 2000,
	size: 512,
	similarity: 0.42,
	thumbnail_url: '/api/patches/42/thumbnail'
};

describe('search URL state', () => {
	test('round-trips query, mode and filters so a reload restores them', () => {
		const query: SearchQuery = {
			q: 'glands',
			mode: 'tissue',
			status: 'signed_out',
			specialty: 'breast',
			assignedTo: 'path-okafor',
			icd10: 'C50',
			patientId: 'pt-0042'
		};
		const url = writeSearchQuery(new URL('http://localhost/search?unrelated=1'), query);
		expect(url.searchParams.get('unrelated')).toBe('1');
		expect(parseSearchQuery(url.searchParams)).toEqual(query);
		expect(searchHref(query)).toBe(
			'/search?q=glands&mode=tissue&status=signed_out&specialty=breast&assigned_to=path-okafor&icd10=C50&patient_id=pt-0042'
		);
	});

	test('reads pathologist_id as an alias and writes assigned_to', () => {
		const parsed = parseSearchQuery(
			new URLSearchParams('q=glands&mode=reports&pathologist_id=path-singh')
		);
		expect(parsed.assignedTo).toBe('path-singh');
		const written = writeSearchQuery(new URL('http://localhost/search'), parsed);
		expect(written.searchParams.get('assigned_to')).toBe('path-singh');
		expect(written.searchParams.get('pathologist_id')).toBeNull();
	});

	test('drops unknown mode, status and specialty', () => {
		expect(
			parseSearchQuery(new URLSearchParams('q=a&mode=slides&status=closed&specialty=neuro'))
		).toEqual({ ...emptySearchQuery(), q: 'a' });
	});

	test('an empty query returns to the worklist', () => {
		expect(globalSearchHref('  keratin nests ')).toBe('/search?q=keratin+nests&mode=reports');
		expect(globalSearchHref('   ')).toBe('/');
		expect(searchHref(emptySearchQuery())).toBe('/');
	});
});

describe('search requests', () => {
	test('reports mode is hybrid corpus search with no context case', () => {
		const body = toReportRequest({
			...emptySearchQuery(),
			q: ' calcifications ',
			specialty: 'thorax',
			icd10: 'C34',
			patientId: 'pt-0042',
			status: 'signed_out',
			assignedTo: 'path-okafor'
		});
		expect(body.text).toBe('calcifications');
		expect(body.mode).toBe('hybrid');
		expect(body.limit).toBe(20);
		expect(body.filters).toEqual({
			status: 'signed_out',
			specialty: ['thorax'],
			icd10_prefix: 'C34',
			patient_id: 'pt-0042'
		});
		expect('context_case_id' in body).toBe(false);
		expect(body.filters != null && 'assigned_to' in body.filters).toBe(false);
	});

	test('tissue mode sends the text query and no context case', () => {
		const body = toPatchRequest({ ...emptySearchQuery(), q: 'keratin nests', mode: 'tissue' });
		expect(body.text).toBe('keratin nests');
		expect(body.scope).toBe('corpus');
		expect(body.limit).toBe(20);
		expect('context_case_id' in body).toBe(false);
		expect('patch_id' in body).toBe(false);
		expect(body.filters ?? null).toBeNull();
	});
});

describe('withheld open-case text', () => {
	test('an open case never keeps report text, conclusion or ICD-10', () => {
		const open = hit(
			{
				passage: {
					section: 'conclusion',
					text: 'SECRET PASSAGE must not render',
					highlights: [[0, 6]]
				},
				score: 2
			},
			{
				status: 'open',
				icd10: 'C50.9',
				conclusion_line: 'SECRET CONCLUSION must not render'
			}
		);
		const presented = presentHit(open, 'breast-FX-B042A');
		expect(presented.open).toBe(true);
		expect(presented.icd10).toBeNull();
		expect(presented.conclusion).toBeNull();
		expect(presented.passage).toBeNull();
		expect(presented.score).toBe(1);
		expect(presented.exact).toBe('case');
		expect(JSON.stringify(presented).includes('SECRET')).toBe(false);
		expect(redactSummary(open.case).icd10).toBeNull();
	});
});

describe('exact matches', () => {
	test('case id, patient and ICD-10 matches sort ahead of other hits', () => {
		const rows = [
			hit({}, { id: 'other-1', icd10: 'C18.0' }),
			hit({}, { id: 'breast-FX-B042B', icd10: 'C50.9' }),
			hit({}, { id: 'breast-FX-B042A', icd10: 'C50.9' })
		];
		expect(sortIds(rows, 'c50.9')).toEqual(['breast-FX-B042B', 'breast-FX-B042A', 'other-1']);
		expect(exactKind('c50.9', rows[1].case)).toBe('icd10');
		expect(exactBadge('icd10')).toBe('Exact ICD-10');
		expect(sortIds(rows, 'BREAST-fx-b042a')[0]).toBe('breast-FX-B042A');
		expect(exactKind('PT-0042', rows[2].case)).toBe('patient');
		expect(exactKind('B042A', rows[2].case)).toBe('case-prefix');
		expect(exactBadge('case-prefix')).toBe('Partial case ID');
	});

	test('a case list lookup is merged in and an open passage is stripped', () => {
		const open = hit(
			{
				passage: {
					section: 'conclusion',
					text: 'SECRET PASSAGE',
					highlights: []
				}
			},
			{ id: 'breast-FX-B042C', status: 'open', icd10: 'C50.9', conclusion_line: 'SECRET' }
		);
		const extra = summary({ id: 'breast-FX-B099Z' });
		const query = parseSearchQuery(new URLSearchParams('q=B099&mode=reports'));
		const merged = mergeCaseLookups([open], [extra, open.case], query);
		expect(merged.map((item) => item.case.id)).toEqual(['breast-FX-B099Z', 'breast-FX-B042C']);
		expect(merged[1].passage).toBeNull();
		expect(merged[1].case.icd10).toBeNull();
		expect(merged[1].case.conclusion_line).toBeNull();
		expect(JSON.stringify(merged).includes('SECRET')).toBe(false);
	});
});

describe('passages and tissue links', () => {
	test('highlight ranges are clamped, merged and left as text', () => {
		const text = 'Small <script>calcifications</script> sit';
		expect(highlightSegments(text, [[6, 14]])).toEqual([
			{ text: 'Small ', mark: false },
			{ text: '<script>', mark: true },
			{ text: 'calcifications</script> sit', mark: false }
		]);
		expect(
			highlightSegments('abcdefghij', [
				[8, 2],
				[-4, 2],
				[3, 6],
				[5, 8],
				[100, 120]
			])
		).toEqual([
			{ text: 'ab', mark: true },
			{ text: 'c', mark: false },
			{ text: 'defgh', mark: true },
			{ text: 'ij', mark: false }
		]);
		expect(highlightSegments('plain', [])).toEqual([{ text: 'plain', mark: false }]);
	});

	test('match badges name keyword, meaning or both', () => {
		expect(matchLabel(['keyword', 'semantic'])).toBe('Both');
		expect(matchLabel(['semantic'])).toBe('Meaning');
		expect(matchLabel(['keyword'])).toBe('Keyword');
		expect(matchLabel(['morphology'])).toBeNull();
		const presented = presentHit(
			hit({
				matched_by: ['semantic'],
				patches: [patch, patch, patch, patch],
				patch_match_count: 9
			}),
			'calcifications'
		);
		expect(presented.matchLabel).toBe('Meaning');
		expect(presented.patches).toHaveLength(3);
		expect(presented.patchCount).toBe(9);
		expect(presented.passage?.sectionLabel).toBe('Microscopic description');
		expect(presented.authorSynthetic).toBe(true);
		expect(presented.specialtyLabel).toBe('Breast');
		expect(presented.ageSex).toBe('61 years · Female');
		expect(presented.conclusion).toBe('Invasive carcinoma of no special type.');
	});

	test('a tissue result links to the patch centre', () => {
		const href = openHref('breast-FX-B042A', 'tissue', patch);
		const url = new URL(href, 'http://local');
		expect(url.pathname).toBe('/cases/breast-FX-B042A');
		expect(url.searchParams.get('slide')).toBe('breast-FX-B042A-s1');
		expect(url.searchParams.get('x')).toBe('1256');
		expect(url.searchParams.get('y')).toBe('2256');
		expect(url.searchParams.get('zoom')).toBe(patchZoom(512));
		expect(url.searchParams.get('patch')).toBe('42');
		expect(openHref('breast-FX-B042A', 'reports', patch)).toBe(
			'/cases/breast-FX-B042A?panel=report'
		);
		expect(openHref('breast-FX-B042A', 'tissue', null)).toBe('/cases/breast-FX-B042A?panel=report');
		expect(patchThumbnail({ ...patch, thumbnail_url: '  ' })).toBe('/api/patches/42/thumbnail');
	});

	test('the summary is a count and a server time, not a probability', () => {
		expect(resultSummary(1, 12)).toBe('1 case · 12 ms server time');
		expect(/%|probability/i.test(resultSummary(2, 40))).toBe(false);
	});
});

describe('search screen states', () => {
	test('distinguishes redirect, loading, error, empty and results', () => {
		expect(searchScreen({ hasQuery: false, searching: false, failed: false, count: 0 })).toBe(
			'redirect'
		);
		expect(searchScreen({ hasQuery: true, searching: true, failed: false, count: 0 })).toBe(
			'loading'
		);
		expect(searchScreen({ hasQuery: true, searching: false, failed: true, count: 0 })).toBe(
			'error'
		);
		expect(searchScreen({ hasQuery: true, searching: false, failed: false, count: 0 })).toBe(
			'empty'
		);
		expect(searchScreen({ hasQuery: true, searching: true, failed: false, count: 2 })).toBe(
			'results'
		);
	});

	test('formats an API error envelope', () => {
		expect(searchErrorMessage({ error: { message: 'text must not be empty' } }, 422)).toBe(
			'text must not be empty'
		);
		expect(searchErrorMessage(null, 500)).toBe(
			'Search failed. The query and filters are unchanged.'
		);
	});
});

function sortIds(rows: CaseHit[], query: string): string[] {
	return mergeCaseLookups(rows, [], { ...emptySearchQuery(), q: query }).map(
		(item) => item.case.id
	);
}
