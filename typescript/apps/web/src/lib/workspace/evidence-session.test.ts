import { afterEach, describe, expect, test } from 'bun:test';
import type { EvidenceTransport } from './evidence-search.js';
import { runEvidenceSearch } from './evidence-search.js';
import { EvidenceSession, clearEvidenceSessions, evidenceSessionFor } from './evidence-session.js';
import {
	emptyFilters,
	type PatchSearchRequest,
	type ReportSearchRequest,
	type SearchResponse,
	type SlideScopeResponse
} from './evidence-model.js';

afterEach(() => {
	clearEvidenceSessions();
});

function corpus(ids: string[]): SearchResponse {
	return {
		query_kind: 'slide',
		hits: ids.map((id) => ({
			author: {
				id: 'path-1',
				name: 'Dr A. Example',
				primary_specialty: 'breast',
				is_synthetic: true
			},
			case: {
				id,
				patient: {
					id: 'pt-9',
					display_label: 'PT-0009',
					case_count: 1,
					is_synthetic_linkage: false,
					sex: 'F'
				},
				specimen_label: null,
				specialty: 'breast',
				patient_sex: 'F',
				icd10: null,
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
				conclusion_line: 'Signed line'
			},
			same_patient: false,
			score: 1,
			matched_by: ['morphology'],
			patches: [
				{
					patch_id: 1,
					slide_id: 'slide-b',
					x: 0,
					y: 0,
					size: 32,
					similarity: 0.5,
					thumbnail_url: '/api/patches/1/thumbnail'
				}
			],
			patch_match_count: 1,
			passage: null
		})),
		total_candidates: ids.length,
		took_ms: 12,
		notice: ids.length === 0 ? null : 'Search stopped after the nearest 200 patches.'
	};
}

function regions(): SlideScopeResponse {
	return {
		query_kind: 'patch',
		patches: [
			{
				patch_id: 9,
				slide_id: 'open-slide',
				x: 4,
				y: 8,
				size: 16,
				similarity: 0.4,
				thumbnail_url: '/api/patches/9/thumbnail'
			}
		],
		total_candidates: 1,
		took_ms: 5
	};
}

function deferred<T>() {
	let resolve: (value: T) => void = () => undefined;
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

async function waitFor(predicate: () => boolean): Promise<void> {
	for (let attempt = 0; attempt < 30; attempt += 1) {
		if (predicate()) return;
		await new Promise((done) => setTimeout(done, 5));
	}
	throw new Error('condition was not met');
}

type HandlerResult = SearchResponse | SlideScopeResponse | { status: number; message: string };

function scripted(
	onPatches: (body: PatchSearchRequest) => HandlerResult | Promise<HandlerResult>,
	onReports?: (body: ReportSearchRequest) => SearchResponse
): {
	transport: EvidenceTransport;
	patchBodies: PatchSearchRequest[];
	reportBodies: ReportSearchRequest[];
} {
	const patchBodies: PatchSearchRequest[] = [];
	const reportBodies: ReportSearchRequest[] = [];
	const transport: EvidenceTransport = {
		async patches(body) {
			patchBodies.push(body);
			const result = await onPatches(body);
			if ('message' in result) {
				return { status: result.status, error: { error: { message: result.message } } };
			}
			return { status: 200, data: result };
		},
		async reports(body) {
			reportBodies.push(body);
			return { status: 200, data: onReports?.(body) ?? corpus(['report-case']) };
		}
	};
	return { transport, patchBodies, reportBodies };
}

describe('evidence session', () => {
	test('keeps the previous list visible until the next search settles', async () => {
		const gate = deferred<void>();
		let phase: 'first' | 'second' = 'first';
		const { transport, patchBodies } = scripted(() => {
			if (phase === 'first') return corpus(['case-a']);
			return gate.promise.then(() => corpus(['case-b']));
		});
		const session = new EvidenceSession('case-open', { transport, warmupMs: 5000 });
		await session.casesLikeSlide('open-slide', null);
		expect(session.visibleHits.map((item) => item.case.id)).toEqual(['case-a']);
		expect(session.phase).toBe('results');
		expect(patchBodies[0]?.slide_id).toBe('open-slide');
		expect(patchBodies[0]?.scope).toBe('corpus');

		phase = 'second';
		const pending = session.runIntent(
			{ kind: 'patch', patchId: '4', slideId: 'open-slide', x: 1, y: 2, size: 8 },
			1,
			null
		);
		await waitFor(() => session.searching);
		expect(session.corpus?.hits[0]?.case.id).toBe('case-a');
		expect(session.phase).toBe('searching');
		gate.resolve();
		await pending;
		expect(session.visibleHits.map((item) => item.case.id)).toEqual(['case-b']);
		expect(session.searching).toBe(false);
	});

	test('a handoff sequence runs once, and a later sequence runs again', async () => {
		const { transport, patchBodies } = scripted(() => corpus(['case-a']));
		const session = new EvidenceSession('case-open', { transport });
		const intent = {
			kind: 'region' as const,
			slideId: 'open-slide',
			x: 1,
			y: 2,
			width: 3,
			height: 4
		};
		await session.runIntent(intent, 3, null);
		await session.runIntent(intent, 3, null);
		expect(patchBodies).toHaveLength(1);
		expect(patchBodies[0]?.region).toEqual({
			slide_id: 'open-slide',
			x: 1,
			y: 2,
			width: 3,
			height: 4
		});
		await session.runIntent(intent, 4, null);
		expect(patchBodies).toHaveLength(2);
		expect(session.consumedSeq).toBe(4);
	});

	test('report handoff switches mode and drops the open case from the list', async () => {
		const { transport, reportBodies } = scripted(
			() => corpus([]),
			() => corpus(['case-open', 'case-other'])
		);
		const session = new EvidenceSession('case-open', { transport });
		await session.runIntent({ kind: 'report_text', text: 'mitotic figures' }, 1, 'pt-1');
		expect(session.mode).toBe('reports');
		expect(session.draft).toBe('mitotic figures');
		expect(reportBodies[0]?.text).toBe('mitotic figures');
		expect(reportBodies[0]?.mode).toBe('hybrid');
		expect(session.visibleHits.map((item) => item.case.id)).toEqual(['case-other']);
		expect(session.notice).toBe('Search stopped after the nearest 200 patches.');
	});

	test('same-patient filter reruns once the open patient id is known', async () => {
		const { transport, patchBodies } = scripted(() => corpus(['case-a']));
		const session = new EvidenceSession('case-open', { transport });
		await session.casesLikeSlide('open-slide', null);
		await session.setFilters({ specialty: null, icd10Prefix: '', samePatient: true }, null);
		expect(patchBodies.at(-1)?.filters ?? null).toBeNull();
		await session.setFilters({ specialty: null, icd10Prefix: '', samePatient: true }, 'pt-9');
		expect(patchBodies.at(-1)?.filters).toEqual({
			specialty: null,
			icd10_prefix: null,
			patient_id: 'pt-9'
		});
		const calls = patchBodies.length;
		await session.setFilters({ specialty: null, icd10Prefix: '', samePatient: true }, 'pt-9');
		expect(patchBodies).toHaveLength(calls);
	});

	test('filters and this-slide scope re-run the active query', async () => {
		const { transport, patchBodies } = scripted((body) =>
			body.scope === 'slide' ? regions() : corpus(['case-a'])
		);
		const session = new EvidenceSession('case-open', { transport });
		await session.runIntent(
			{ kind: 'patch', patchId: '8', slideId: 'open-slide', x: 0, y: 0, size: 16 },
			1,
			'pt-1'
		);
		await session.setFilters(
			{ specialty: 'breast', icd10Prefix: 'c50', samePatient: true },
			'pt-1'
		);
		expect(patchBodies.at(-1)?.filters).toEqual({
			specialty: ['breast'],
			icd10_prefix: 'C50',
			patient_id: 'pt-1'
		});
		await session.setScope('slide', 'pt-1');
		expect(session.regions?.patches).toHaveLength(1);
		expect(session.corpus).toBeNull();
		expect(patchBodies.at(-1)?.scope).toBe('slide');
		expect(session.footer).toBe('1 region · 5 ms');
	});

	test('this-slide scope is refused for a whole-slide query', async () => {
		const { transport, patchBodies } = scripted(() => corpus(['case-a']));
		const session = new EvidenceSession('case-open', { transport });
		await session.casesLikeSlide('open-slide', null);
		await session.setScope('slide', null);
		expect(patchBodies).toHaveLength(1);
		expect(session.scope).toBe('corpus');
		expect(session.scopeNote).toContain('other signed-out cases');
	});

	test('a failed search keeps the active query and the previous results', async () => {
		let fail = false;
		const { transport } = scripted(() => {
			if (fail) return { status: 422, message: 'Region covers no tissue patches.' };
			return corpus(['case-a']);
		});
		const session = new EvidenceSession('case-open', { transport });
		await session.casesLikeSlide('open-slide', null);
		fail = true;
		await session.runIntent(
			{ kind: 'region', slideId: 'open-slide', x: 0, y: 0, width: 2, height: 2 },
			2,
			null
		);
		expect(session.failure).toEqual({
			kind: 'no-tissue',
			message: 'Region covers no tissue patches.'
		});
		expect(session.phase).toBe('no-tissue');
		expect(session.query?.kind).toBe('region');
		expect(session.visibleHits).toHaveLength(1);
		expect(session.searching).toBe(false);
	});

	test('clear drops the query, and a late response cannot restore it', async () => {
		const gate = deferred<void>();
		const transport: EvidenceTransport = {
			async patches() {
				await gate.promise;
				return { status: 200, data: corpus(['case-a']) };
			},
			async reports() {
				return { status: 200, data: corpus([]) };
			}
		};
		const session = new EvidenceSession('case-open', { transport });
		const pending = session.casesLikeSlide('open-slide', null);
		await waitFor(() => session.searching);
		session.clear();
		gate.resolve();
		await pending;
		expect(session.query).toBeNull();
		expect(session.corpus).toBeNull();
		expect(session.phase).toBe('idle');
	});

	test('the first slow text query warns that the encoder is warming up', async () => {
		const gate = deferred<void>();
		const transport: EvidenceTransport = {
			async patches() {
				await gate.promise;
				return { status: 200, data: corpus(['case-a']) };
			},
			async reports() {
				return { status: 200, data: corpus([]) };
			}
		};
		const session = new EvidenceSession('case-open', { transport, warmupMs: 20 });
		session.draft = 'sheets of cells';
		const pending = session.submitText(null);
		await waitFor(() => session.warming);
		expect(session.warming).toBe(true);
		gate.resolve();
		await pending;
		expect(session.warming).toBe(false);
		expect(session.query?.kind).toBe('tissue-text');

		const slow = deferred<void>();
		const second = new EvidenceSession('case-open-2', {
			transport: {
				async patches() {
					await slow.promise;
					return { status: 200, data: corpus(['case-b']) };
				},
				async reports() {
					return { status: 200, data: corpus([]) };
				}
			},
			warmupMs: 20
		});
		second.draft = 'more text';
		const again = second.submitText(null);
		await new Promise((done) => setTimeout(done, 40));
		expect(second.warming).toBe(false);
		slow.resolve();
		await again;
	});

	test('the same case session is restored when the panel asks again', async () => {
		const { transport } = scripted(() => corpus(['case-a']));
		const first = evidenceSessionFor('case-open', transport);
		await first.casesLikeSlide('open-slide', null);
		const second = evidenceSessionFor('case-open');
		expect(second).toBe(first);
		expect(second.visibleHits.map((item) => item.case.id)).toEqual(['case-a']);
		expect(second.filters).toEqual(emptyFilters());
	});
});

describe('evidence search runner', () => {
	test('splits corpus hits from this-slide patches and surfaces transport failures', async () => {
		const controller = new AbortController();
		const corpusResult = await runEvidenceSearch(
			{
				async patches() {
					return { status: 200, data: corpus(['case-a']) };
				},
				async reports() {
					return { status: 500, error: { error: { message: 'Encoder unavailable.' } } };
				}
			},
			{
				endpoint: 'patches',
				scope: 'corpus',
				body: { context_case_id: 'case-open', scope: 'corpus', limit: 20, slide_id: 's' }
			},
			controller.signal
		);
		expect(corpusResult.ok).toBe(true);
		if (corpusResult.ok) expect(corpusResult.corpus?.hits).toHaveLength(1);

		const slideResult = await runEvidenceSearch(
			{
				async patches() {
					return { status: 200, data: regions() };
				},
				async reports() {
					return { status: 200, data: corpus([]) };
				}
			},
			{
				endpoint: 'patches',
				scope: 'slide',
				body: { context_case_id: 'case-open', scope: 'slide', limit: 20, patch_id: 1 }
			},
			controller.signal
		);
		expect(slideResult.ok).toBe(true);
		if (slideResult.ok) expect(slideResult.regions?.patches[0]?.patch_id).toBe(9);

		const failed = await runEvidenceSearch(
			{
				async patches() {
					return { status: 200, data: corpus([]) };
				},
				async reports() {
					return { status: 503, error: { error: { message: 'Encoder unavailable.' } } };
				}
			},
			{
				endpoint: 'reports',
				scope: 'corpus',
				body: { text: 'glands', mode: 'hybrid', limit: 20 }
			},
			controller.signal
		);
		expect(failed).toEqual({
			ok: false,
			failure: { kind: 'error', message: 'Encoder unavailable.' }
		});
	});
});
