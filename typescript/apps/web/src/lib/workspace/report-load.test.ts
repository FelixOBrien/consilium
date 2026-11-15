import { afterEach, describe, expect, test } from 'bun:test';
import { loadCaseDetail, loadCaseReport } from './report-load.js';

const originalFetch = globalThis.fetch;

afterEach(() => {
	globalThis.fetch = originalFetch;
});

function jsonResponse(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

describe('report and case loads', () => {
	test('loads a signed report and an open report without extra fields', async () => {
		const seen: string[] = [];
		globalThis.fetch = async (input) => {
			const url = input instanceof Request ? input.url : String(input);
			seen.push(url);
			if (url.endsWith('/api/cases/case-signed/report')) {
				return jsonResponse(200, {
					id: 'case-signed-r1',
					case_id: 'case-signed',
					status: 'signed',
					body: 'Full text.',
					clinical_history: 'History.',
					gross_description: null,
					microscopic_description: null,
					conclusion: 'A conclusion line.',
					additional_info: null,
					icd10: null,
					signed_at: '2025-08-04T00:00:00.000Z',
					is_synthetic_author: true,
					author: {
						id: 'path-okafor',
						name: 'Dr A. Okafor',
						is_synthetic: true,
						primary_specialty: 'breast'
					}
				});
			}
			return jsonResponse(200, {
				case_id: 'case-open',
				status: 'none',
				clinical_history: 'Imaging prompted the request.'
			});
		};

		const signed = await loadCaseReport('case-signed');
		const open = await loadCaseReport('case-open');
		expect(signed.phase).toBe('ready');
		if (signed.phase === 'ready') expect(signed.report.status).toBe('signed');
		expect(open.phase).toBe('ready');
		if (open.phase === 'ready' && open.report.status === 'none') {
			expect(open.report.clinical_history).toBe('Imaging prompted the request.');
			expect(Object.keys(open.report).sort()).toEqual(['case_id', 'clinical_history', 'status']);
		} else {
			throw new Error('expected an unreported case');
		}
		expect(seen.some((url) => url.endsWith('/api/cases/case-signed/report'))).toBe(true);
	});

	test('maps 404, a failed response and a network error', async () => {
		globalThis.fetch = async () =>
			jsonResponse(404, { error: { code: 'not_found', message: 'missing' } });
		expect(await loadCaseReport('missing')).toEqual({ phase: 'not-found' });

		globalThis.fetch = async () => new Response('nope', { status: 500 });
		expect(await loadCaseReport('broken')).toEqual({ phase: 'error' });

		globalThis.fetch = async () => {
			throw new Error('offline');
		};
		expect(await loadCaseDetail('offline')).toEqual({ phase: 'error' });
	});

	test('loads a case summary', async () => {
		globalThis.fetch = async (input) => {
			const url = input instanceof Request ? input.url : String(input);
			expect(url.endsWith('/api/cases/case-1')).toBe(true);
			expect(url.includes('/report')).toBe(false);
			return jsonResponse(200, {
				id: 'case-1',
				status: 'open',
				icd10: 'C50.9',
				specialty: 'breast',
				specimen_label: 'Core biopsy',
				report_status: 'none',
				accessioned_at: '2026-11-02T00:00:00.000Z',
				patient_age: 61,
				patient_sex: 'F',
				prior_case_count: 2,
				slide_count: 1,
				slides: [],
				conclusion_line: null,
				thumbnail_url: null,
				assigned_to: {
					id: 'path-okafor',
					name: 'Dr A. Okafor',
					is_synthetic: true,
					primary_specialty: 'breast'
				},
				patient: {
					id: 'pt-0042',
					display_label: 'PT-0042',
					case_count: 3,
					is_synthetic_linkage: false,
					sex: 'F'
				}
			});
		};
		const result = await loadCaseDetail('case-1');
		expect(result.phase).toBe('ready');
		if (result.phase === 'ready') {
			expect(result.detail.patient.id).toBe('pt-0042');
			expect(result.detail.icd10).toBe('C50.9');
		}
	});
});
