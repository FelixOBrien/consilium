import { api } from '#lib/api/client.js';
import type { CaseDetail, CaseReport } from './report-text.js';

export type ReportLoad =
	| { phase: 'loading' }
	| { phase: 'not-found' }
	| { phase: 'error' }
	| { phase: 'ready'; report: CaseReport };

export type CaseLoad =
	| { phase: 'loading' }
	| { phase: 'not-found' }
	| { phase: 'error' }
	| { phase: 'ready'; detail: CaseDetail };

export async function loadCaseReport(
	caseId: string
): Promise<Exclude<ReportLoad, { phase: 'loading' }>> {
	try {
		const result = await api.GET('/api/cases/{case_id}/report', {
			params: { path: { case_id: caseId } }
		});
		if (result.response.status === 404) return { phase: 'not-found' };
		if (!result.data) return { phase: 'error' };
		return { phase: 'ready', report: result.data };
	} catch {
		return { phase: 'error' };
	}
}

export async function loadCaseDetail(
	caseId: string
): Promise<Exclude<CaseLoad, { phase: 'loading' }>> {
	try {
		const result = await api.GET('/api/cases/{case_id}', {
			params: { path: { case_id: caseId } }
		});
		if (result.response.status === 404) return { phase: 'not-found' };
		if (!result.data) return { phase: 'error' };
		return { phase: 'ready', detail: result.data };
	} catch {
		return { phase: 'error' };
	}
}
