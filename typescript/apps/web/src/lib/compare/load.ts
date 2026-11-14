import { api } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';

export type SlideDetail = components['schemas']['SlideDetail'];

export type SlideLoad =
	| { status: 'ready'; slide: SlideDetail; specimenLabel: string | null }
	| { status: 'not-found'; message: string }
	| { status: 'not-ready'; message: string }
	| { status: 'error'; message: string };

type ErrorBody = { code?: string; message?: string };

export async function loadSlide(slideId: string): Promise<SlideLoad> {
	const { data, error, response } = await api.GET('/api/slides/{slide_id}', {
		params: { path: { slide_id: slideId } }
	});
	const body = errorBody(error);
	if (response.status === 404 || body?.code === 'not_found') {
		return { status: 'not-found', message: body?.message ?? 'Slide not found.' };
	}
	if (response.status === 409 || body?.code === 'not_ready') {
		return {
			status: 'not-ready',
			message: body?.message ?? 'Slide is not ready.'
		};
	}
	if (!response.ok || !data) {
		return {
			status: 'error',
			message: body?.message ?? 'The slide could not be loaded.'
		};
	}
	if (data.status !== 'ready') {
		return { status: 'not-ready', message: `Slide status is ${data.status}.` };
	}
	return {
		status: 'ready',
		slide: data,
		specimenLabel: await specimenLabel(data.case_id)
	};
}

async function specimenLabel(caseId: string): Promise<string | null> {
	const { data, response } = await api.GET('/api/cases/{case_id}', {
		params: { path: { case_id: caseId } }
	});
	if (!response.ok || !data) return null;
	return data.specimen_label;
}

function errorBody(error: unknown): ErrorBody | null {
	if (!error || typeof error !== 'object' || !('error' in error)) return null;
	const inner = (error as { error?: ErrorBody }).error;
	return inner ?? null;
}
