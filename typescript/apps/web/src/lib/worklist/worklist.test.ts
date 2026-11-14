import { afterEach, describe, expect, test } from 'bun:test';
import { forgetActingUser, rememberActingUser } from '#lib/identity/acting-user.js';
import { RESEARCH_NOTICE, SYNTHETIC_ROSTER_NOTICE } from '#lib/identity/copy.js';
import { appendCases, presentCase, visibleConclusion } from './present.js';
import {
	clearedFilters,
	emptyWorklistQuery,
	parseWorklistQuery,
	writeWorklistQuery,
	type CaseSummary,
	type WorklistQuery
} from './query.js';
import { worklistScreen } from './screen.js';
import {
	clearWorklistTallies,
	fetchCasePage,
	loadNextPage,
	tallyView,
	type CaseSource
} from './load.js';

function caseSummary(overrides: Partial<CaseSummary> = {}): CaseSummary {
	return {
		id: 'breast-TCGA-A2-0002',
		patient: {
			id: 'pt-0042',
			display_label: 'PT-0042',
			case_count: 2,
			is_synthetic_linkage: true,
			sex: 'F'
		},
		specimen_label: 'Excision',
		specialty: 'breast',
		patient_age: 61,
		patient_sex: 'F',
		icd10: null,
		status: 'open',
		assigned_to: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		accessioned_at: '2026-11-01T00:00:00Z',
		slide_count: 1,
		thumbnail_url: '/api/slides/breast-TCGA-A2-0002-s1/thumbnail',
		conclusion_line: 'This must not be shown for an open case.',
		...overrides
	};
}

function pageOf(items: CaseSummary[], next: string | null = null) {
	return { items, next_cursor: next };
}

afterEach(() => {
	forgetActingUser({
		getItem: () => null,
		setItem: () => undefined,
		removeItem: () => undefined
	});
	clearWorklistTallies();
});

describe('worklist URL state', () => {
	test('round-trips view and filters so a reload restores them', () => {
		const query: WorklistQuery = {
			view: 'all',
			status: 'signed_out',
			specialty: 'breast',
			assignedTo: 'path-okafor',
			icd10: 'C50',
			patientId: 'pt-0042'
		};
		const url = writeWorklistQuery(new URL('http://localhost/?unrelated=1'), query);
		expect(url.searchParams.get('unrelated')).toBe('1');
		expect(parseWorklistQuery(url.searchParams)).toEqual(query);
	});

	test('defaults to My cases and drops unknown filter values', () => {
		const params = new URLSearchParams('status=closed&specialty=neuro&view=elsewhere');
		expect(parseWorklistQuery(params)).toEqual(emptyWorklistQuery());
	});

	test('clear filters keeps the view and removes every filter', () => {
		const cleared = clearedFilters({
			...emptyWorklistQuery(),
			view: 'all',
			status: 'open',
			specialty: 'skin',
			assignedTo: 'path-singh',
			icd10: 'C44',
			patientId: 'pt-0007'
		});
		expect(cleared).toEqual({ ...emptyWorklistQuery(), view: 'all' });
	});
});

describe('worklist rows', () => {
	test('an open case never shows a conclusion, even if one is present', () => {
		const row = presentCase(caseSummary());
		expect(row.conclusion).toBeNull();
		expect(visibleConclusion(caseSummary())).toBeNull();
		expect(row.patientLabel).toBe('PT-0042');
		expect(row.patientHref).toBe('/patients/pt-0042');
		expect(row.caseHref).toBe('/cases/breast-TCGA-A2-0002');
		expect(row.priorCases).toBe(true);
		expect(row.icd10).toBeNull();
		expect(row.pathologistSynthetic).toBe(true);
	});

	test('a signed-out case shows the conclusion line', () => {
		const row = presentCase(
			caseSummary({
				id: 'breast-TCGA-A2-0001',
				status: 'signed_out',
				icd10: 'C50.9',
				conclusion_line: 'Invasive carcinoma with glandular differentiation.'
			})
		);
		expect(row.conclusion).toBe('Invasive carcinoma with glandular differentiation.');
		expect(row.statusLabel).toBe('Signed out');
	});
});

describe('worklist screens', () => {
	const base = {
		loading: false,
		failed: false,
		itemCount: 0,
		query: emptyWorklistQuery(),
		corpusEmpty: false as boolean | null,
		actingName: 'Dr C. Nowak'
	};

	test('loading, error, empty filter, empty queue and no data are each reachable', () => {
		expect(worklistScreen({ ...base, loading: true }).kind).toBe('loading');
		expect(worklistScreen({ ...base, failed: true, corpusEmpty: null }).kind).toBe('error');
		expect(
			worklistScreen({
				...base,
				query: { ...emptyWorklistQuery(), specialty: 'hematologic' }
			}).kind
		).toBe('empty-filter');
		expect(worklistScreen(base).kind).toBe('empty-queue');
		expect(worklistScreen({ ...base, corpusEmpty: true }).kind).toBe('no-data');
		expect(worklistScreen({ ...base, itemCount: 2 }).kind).toBe('ready');
	});

	test('empty states offer the action named in the screen doc', () => {
		const filtered = worklistScreen({
			...base,
			query: { ...emptyWorklistQuery(), status: 'open', icd10: 'C34' }
		});
		expect(filtered.kind === 'empty-filter' && filtered.action).toBe('Clear filters');
		const queue = worklistScreen(base);
		expect(queue.kind === 'empty-queue' && queue.description).toContain('Dr C. Nowak');
		expect(queue.kind === 'empty-queue' && queue.action).toBe('View all cases');
		const missing = worklistScreen({ ...base, corpusEmpty: true });
		expect(missing.kind === 'no-data' && missing.action).toBe('Open ingestion');
		const error = worklistScreen({ ...base, failed: true, corpusEmpty: null });
		expect(error.kind === 'error' && error.action).toBe('Retry');
		expect(error.kind === 'error' && error.description).toContain('filters have been kept');
	});
});

describe('cursor pagination', () => {
	test('follows next_cursor and appends the next page', async () => {
		const calls: Array<string | null> = [];
		const source: CaseSource = {
			async list(_query, cursor) {
				calls.push(cursor);
				if (!cursor) return pageOf([caseSummary({ id: 'case-1' })], 'case-1');
				return pageOf([caseSummary({ id: 'case-2', conclusion_line: null })], null);
			}
		};
		const first = await source.list(emptyWorklistQuery(), null, 50);
		const next = await loadNextPage(
			source,
			emptyWorklistQuery(),
			first.next_cursor ?? '',
			first.items
		);
		expect(calls).toEqual([null, 'case-1']);
		expect(next.items.map((item) => item.id)).toEqual(['case-1', 'case-2']);
		expect(next.nextCursor).toBeNull();
		expect(appendCases(next.items, next.items)).toHaveLength(2);
	});

	test('counts a view by walking cursors, including open cases', async () => {
		const source: CaseSource = {
			async list(_query, cursor) {
				if (!cursor) {
					return pageOf(
						[
							caseSummary({ id: 'open-1', status: 'open' }),
							caseSummary({ id: 'signed-1', status: 'signed_out' })
						],
						'signed-1'
					);
				}
				return pageOf([caseSummary({ id: 'open-2', status: 'open' })], null);
			}
		};
		const tally = await tallyView(source, 'mine', 5);
		expect(tally).toEqual({ total: 3, open: 2, truncated: false });
	});

	test('the cases request carries the cursor, filters and X-User-Id', async () => {
		rememberActingUser('path-okafor', {
			getItem: () => 'path-okafor',
			setItem: () => undefined,
			removeItem: () => undefined
		});
		let url = '';
		const original = globalThis.fetch;
		globalThis.fetch = async (input, init) => {
			const request = new Request(input, init);
			url = request.url;
			expect(request.headers.get('X-User-Id')).toBe('path-okafor');
			return new Response(
				JSON.stringify({
					items: [],
					next_cursor: null
				}),
				{ status: 200, headers: { 'content-type': 'application/json' } }
			);
		};
		try {
			await fetchCasePage(
				{
					view: 'all',
					status: 'signed_out',
					specialty: 'thorax',
					assignedTo: 'path-adebayo',
					icd10: 'C34',
					patientId: 'pt-0007'
				},
				'thorax-TCGA-38-4631',
				50
			);
		} finally {
			globalThis.fetch = original;
		}
		const parsed = new URL(url);
		expect(parsed.pathname).toBe('/api/cases');
		expect(parsed.searchParams.get('view')).toBe('all');
		expect(parsed.searchParams.get('status')).toBe('signed_out');
		expect(parsed.searchParams.get('specialty')).toBe('thorax');
		expect(parsed.searchParams.get('assigned_to')).toBe('path-adebayo');
		expect(parsed.searchParams.get('icd10')).toBe('C34');
		expect(parsed.searchParams.get('patient_id')).toBe('pt-0007');
		expect(parsed.searchParams.get('cursor')).toBe('thorax-TCGA-38-4631');
		expect(parsed.searchParams.get('limit')).toBe('50');
	});
});

describe('required notices', () => {
	test('the shell copy marks the prototype and the synthetic roster', () => {
		expect(RESEARCH_NOTICE.toLowerCase()).toContain('research prototype');
		expect(RESEARCH_NOTICE.toLowerCase()).toContain('not for clinical use');
		expect(SYNTHETIC_ROSTER_NOTICE.toLowerCase()).toContain('synthetic');
	});
});
