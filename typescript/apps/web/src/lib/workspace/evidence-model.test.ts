import { describe, expect, test } from 'bun:test';
import { formatZoom } from './viewport-url.js';
import {
	PATCH_FRAME_PX,
	buildSearch,
	caseOpenQuery,
	classifySearchFailure,
	consultCaseIds,
	effectiveScope,
	emptyFilters,
	filtersActive,
	isSlideScopeResponse,
	messageFromEnvelope,
	parseSpecialty,
	passageSegments,
	patchCountLabel,
	presentCase,
	presentQuery,
	presentRankScore,
	presentRegions,
	presentScore,
	queryFromIntent,
	resultFooter,
	searchMarkers,
	shouldWarnEncoderWarmup,
	slideScopeUnavailableReason,
	toSearchFilters,
	visibleCaseHits,
	type BuiltSearch,
	type CaseHit,
	type PatchHit,
	type SearchResponse,
	type SlideScopeResponse
} from './evidence-model.js';

function patchesOf(
	built: BuiltSearch | { error: string }
): Extract<BuiltSearch, { endpoint: 'patches' }> {
	if ('error' in built) throw new Error(built.error);
	if (built.endpoint !== 'patches') throw new Error('expected a patch search');
	return built;
}

function reportsOf(
	built: BuiltSearch | { error: string }
): Extract<BuiltSearch, { endpoint: 'reports' }> {
	if ('error' in built) throw new Error(built.error);
	if (built.endpoint !== 'reports') throw new Error('expected a report search');
	return built;
}

function plainLabel(label: string): boolean {
	return !/\d|%|percent|probab|confidence|likelihood/i.test(label);
}

function patch(overrides: Partial<PatchHit> = {}): PatchHit {
	return {
		patch_id: 7,
		slide_id: 'slide-b',
		x: 100,
		y: 200,
		size: 80,
		similarity: 0.91,
		thumbnail_url: '/api/patches/7/thumbnail',
		...overrides
	};
}

function hit(overrides: Partial<CaseHit> = {}): CaseHit {
	return {
		author: {
			id: 'path-1',
			name: 'Dr A. Example',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		case: {
			id: 'breast-other',
			patient: {
				id: 'pt-9',
				display_label: 'PT-0009',
				case_count: 2,
				is_synthetic_linkage: true,
				sex: 'F'
			},
			specimen_label: 'Excision',
			specialty: 'breast',
			patient_age: 60,
			patient_sex: 'F',
			icd10: 'C50.9',
			status: 'signed_out',
			assigned_to: {
				id: 'path-1',
				name: 'Dr A. Example',
				primary_specialty: 'breast',
				is_synthetic: true
			},
			accessioned_at: '2024-01-01T00:00:00Z',
			slide_count: 1,
			thumbnail_url: null,
			conclusion_line: 'Invasive carcinoma, signed report.'
		},
		same_patient: false,
		score: 1,
		matched_by: ['morphology'],
		patches: [patch()],
		patch_match_count: 4,
		passage: null,
		...overrides
	};
}

describe('evidence queries', () => {
	test('maps viewer and report handoffs onto one query', () => {
		expect(
			queryFromIntent({
				kind: 'patch',
				patchId: '12',
				slideId: 's1',
				x: 1,
				y: 2,
				size: 32
			})
		).toEqual({ kind: 'patch', patchId: '12', slideId: 's1', x: 1, y: 2, size: 32 });
		expect(
			queryFromIntent({ kind: 'region', slideId: 's1', x: 3, y: 4, width: 5, height: 6 }).kind
		).toBe('region');
		expect(queryFromIntent({ kind: 'report_text', text: '  glands  ' })).toEqual({
			kind: 'report-text',
			text: 'glands'
		});
	});

	test('cases like this slide searches the open slide in the corpus', () => {
		const built = patchesOf(
			buildSearch({
				query: { kind: 'slide', slideId: 'open-slide' },
				scope: 'slide',
				filters: emptyFilters(),
				contextCaseId: 'case-open',
				patientId: 'pt-1'
			})
		);
		expect(built.scope).toBe('corpus');
		expect(built.body.slide_id).toBe('open-slide');
		expect(built.body.scope).toBe('corpus');
		expect(built.body.patch_id ?? null).toBeNull();
		expect(built.body.text ?? null).toBeNull();
		expect(built.body.context_case_id).toBe('case-open');
	});

	test('patch, region and tissue text build one patch-search body each', () => {
		const patchSearch = patchesOf(
			buildSearch({
				query: { kind: 'patch', patchId: '15', slideId: 's', x: 0, y: 0, size: 8 },
				scope: 'corpus',
				filters: emptyFilters(),
				contextCaseId: 'case-open',
				patientId: null
			})
		);
		expect(patchSearch.body.patch_id).toBe(15);
		expect(patchSearch.body.region ?? null).toBeNull();

		const regionSearch = patchesOf(
			buildSearch({
				query: { kind: 'region', slideId: 's', x: 1.4, y: 2.6, width: 10.2, height: 11.8 },
				scope: 'slide',
				filters: emptyFilters(),
				contextCaseId: 'case-open',
				patientId: null
			})
		);
		expect(regionSearch.body.scope).toBe('slide');
		expect(regionSearch.body.region).toEqual({
			slide_id: 's',
			x: 1,
			y: 3,
			width: 10,
			height: 12
		});

		const textSearch = patchesOf(
			buildSearch({
				query: { kind: 'tissue-text', text: 'glandular structures' },
				scope: 'slide',
				filters: { specialty: 'breast', icd10Prefix: ' c50 ', samePatient: true },
				contextCaseId: 'case-open',
				patientId: 'pt-1'
			})
		);
		expect(textSearch.body.text).toBe('glandular structures');
		expect(textSearch.body.scope).toBe('slide');
		expect(textSearch.body.filters).toEqual({
			specialty: ['breast'],
			icd10_prefix: 'C50',
			patient_id: 'pt-1'
		});
	});

	test('report text uses the report endpoint and cannot take slide scope', () => {
		const built = reportsOf(
			buildSearch({
				query: { kind: 'report-text', text: 'lymphovascular invasion' },
				scope: 'slide',
				filters: emptyFilters(),
				contextCaseId: 'case-open',
				patientId: null
			})
		);
		expect(built.scope).toBe('corpus');
		expect(built.body.text).toBe('lymphovascular invasion');
		expect(built.body.mode).toBe('hybrid');
		expect(built.body.context_case_id).toBe('case-open');
		expect(built.body.limit).toBe(20);
		expect(effectiveScope({ kind: 'report-text', text: 'a' }, 'slide')).toBe('corpus');
		expect(slideScopeUnavailableReason({ kind: 'report-text', text: 'a' })).toContain('Report');
		expect(slideScopeUnavailableReason({ kind: 'slide', slideId: 's' })).toContain(
			'other signed-out'
		);
	});

	test('rejects an empty region and a non-numeric patch id', () => {
		const region = buildSearch({
			query: { kind: 'region', slideId: 's', x: 0, y: 0, width: 0, height: 4 },
			scope: 'corpus',
			filters: emptyFilters(),
			contextCaseId: 'case-open',
			patientId: null
		});
		expect(region).toEqual({ error: 'The region is empty.' });
		const badPatch = buildSearch({
			query: { kind: 'patch', patchId: 'nope', slideId: 's', x: 0, y: 0, size: 8 },
			scope: 'corpus',
			filters: emptyFilters(),
			contextCaseId: 'case-open',
			patientId: null
		});
		expect('error' in badPatch).toBe(true);
	});

	test('same-patient filter is the context patient id and is omitted when off', () => {
		expect(toSearchFilters(emptyFilters(), 'pt-1')).toBeNull();
		expect(filtersActive(emptyFilters())).toBe(false);
		expect(filtersActive({ specialty: null, icd10Prefix: '', samePatient: true })).toBe(true);
		expect(parseSpecialty('breast')).toBe('breast');
		expect(parseSpecialty('nope')).toBeNull();
	});
});

describe('evidence presentation', () => {
	test('score tiers are words and bars, never a number or a probability', () => {
		expect(presentScore(1)).toEqual({ tier: 'closest', label: 'Closest', bar: 4 });
		expect(presentScore(0.84).label).toBe('Strong');
		expect(presentScore(0.6).tier).toBe('strong');
		expect(presentScore(0.59).tier).toBe('related');
		expect(presentScore(0.35).tier).toBe('related');
		expect(presentScore(0).tier).toBe('distant');
		for (const score of [0, 0.2, 0.5, 0.84, 1, Number.NaN]) {
			expect(plainLabel(presentScore(score).label)).toBe(true);
		}
		expect(presentRankScore(0).label).toBe('Closest');
		expect(presentRankScore(3).label).toBe('Distant');
		expect(plainLabel(presentRankScore(1).label)).toBe(true);
	});

	test('open url centres on the stored patch', () => {
		const target = patch({ x: 100, y: 200, size: 80, patch_id: 7, slide_id: 'slide-b' });
		const params = new URLSearchParams(caseOpenQuery(target));
		expect(params.get('slide')).toBe('slide-b');
		expect(params.get('x')).toBe('140');
		expect(params.get('y')).toBe('240');
		expect(params.get('zoom')).toBe(formatZoom(PATCH_FRAME_PX / 80));
		expect(params.get('patch')).toBe('7');
	});

	test('highlights merge overlaps and ignore ranges outside the passage', () => {
		expect(
			passageSegments('abcdef', [
				[2, 4],
				[3, 5],
				[8, 10],
				[-1, 1]
			])
		).toEqual([
			{ text: 'a', marked: true },
			{ text: 'b', marked: false },
			{ text: 'cde', marked: true },
			{ text: 'f', marked: false }
		]);
		expect(passageSegments('plain', [])).toEqual([{ text: 'plain', marked: false }]);
	});

	test('signed-out hits keep the report line, author and at most three patches', () => {
		const extra = [1, 2, 3, 4].map((id) => patch({ patch_id: id }));
		const row = presentCase(
			hit({
				same_patient: true,
				patches: extra,
				patch_match_count: 9,
				matched_by: ['keyword', 'semantic'],
				passage: {
					section: 'microscopic_description',
					text: 'See glands',
					highlights: [[4, 10]]
				}
			})
		);
		expect(row.patientLabel).toBe('PT-0009');
		expect(row.samePatient).toBe(true);
		expect(row.syntheticLinkage).toBe(true);
		expect(row.specialty).toBe('Breast');
		expect(row.icd10).toBe('C50.9');
		expect(row.conclusion).toBe('Invasive carcinoma, signed report.');
		expect(row.authorSynthetic).toBe(true);
		expect(row.matchedBy).toEqual(['Keyword', 'Meaning']);
		expect(row.patches).toHaveLength(3);
		expect(row.patchCountLabel).toBe('9 matching patches');
		expect(row.passage?.section).toBe('Microscopic description');
		expect(row.passage?.segments[1]).toEqual({ text: 'glands', marked: true });
		expect(row.peekPatch).toEqual({ id: '1', slide_id: 'slide-b', x: 100, y: 200, size: 80 });
		expect(row.openQuery).toContain('slide=slide-b');
	});

	test('open cases and the context case never show withheld report text', () => {
		const open = presentCase(
			hit({
				case: {
					...hit().case,
					id: 'case-open',
					status: 'open',
					icd10: 'C50',
					conclusion_line: 'This must stay hidden.'
				},
				passage: { section: 'conclusion', text: 'Hidden conclusion', highlights: [] }
			})
		);
		expect(open.conclusion).toBeNull();
		expect(open.icd10).toBeNull();
		expect(open.passage).toBeNull();
		expect(open.patches).toEqual([]);
		expect(open.openQuery).toBe('');

		const hits = [
			hit({ case: { ...hit().case, id: 'case-open' } }),
			hit(),
			hit({
				case: { ...hit().case, id: 'still-open', status: 'open', conclusion_line: 'Secret' }
			})
		];
		expect(visibleCaseHits(hits, 'case-open').map((item) => item.case.id)).toEqual([
			'breast-other'
		]);
		expect(consultCaseIds(hits)).toEqual(['case-open', 'breast-other']);
	});

	test('this-slide regions become viewer markers and fly targets at the stored box', () => {
		const regions = presentRegions([
			patch({ patch_id: 3, x: 10, y: 20, size: 40 }),
			patch({ patch_id: 4, x: 50, y: 60, size: 40 })
		]);
		expect(regions[0]?.label).toBe('Region 1');
		expect(regions[0]?.fly).toEqual({
			slideId: 'slide-b',
			x: 10,
			y: 20,
			width: 40,
			height: 40,
			markPatch: { id: '3', x: 10, y: 20, size: 40 }
		});
		expect(searchMarkers([patch({ patch_id: 3, x: 10, y: 20, size: 40 })])).toEqual([
			{
				id: '3',
				x: 10,
				y: 20,
				width: 40,
				height: 40,
				rank: 1,
				label: 'Region 1'
			}
		]);
		expect(regions[1]?.score.label).toBe('Strong');
	});

	test('query copy and the footer name what was searched', () => {
		expect(presentQuery({ kind: 'slide', slideId: 's' }).label).toBe('This slide');
		expect(presentQuery({ kind: 'tissue-text', text: 'cords' }).kicker).toContain('description');
		expect(patchCountLabel(1)).toBe('1 matching patch');
		expect(resultFooter(1, 42, 'cases')).toBe('1 case · 42 ms');
		expect(resultFooter(2, 18, 'regions')).toBe('2 regions · 18 ms');
		expect(shouldWarnEncoderWarmup(true, 3000)).toBe(true);
		expect(shouldWarnEncoderWarmup(false, 9000)).toBe(false);
		expect(shouldWarnEncoderWarmup(true, 2999)).toBe(false);
	});

	test('classifies a bare region and reads the error envelope', () => {
		expect(classifySearchFailure(422, 'Region covers no tissue patches.')).toEqual({
			kind: 'no-tissue',
			message: 'Region covers no tissue patches.'
		});
		expect(classifySearchFailure(500, 'nope').kind).toBe('error');
		expect(messageFromEnvelope({ error: { message: 'Slide has no tissue embedding.' } })).toBe(
			'Slide has no tissue embedding.'
		);
		expect(messageFromEnvelope(null)).toBe('The search failed.');
		const corpus: SearchResponse = {
			query_kind: 'slide',
			hits: [],
			total_candidates: 0,
			took_ms: 1
		};
		const regions: SlideScopeResponse = {
			query_kind: 'patch',
			patches: [],
			total_candidates: 0,
			took_ms: 1
		};
		expect(isSlideScopeResponse(corpus)).toBe(false);
		expect(isSlideScopeResponse(regions)).toBe(true);
	});
});
