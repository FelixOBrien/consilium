import { api } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';

export type AnnotationRecord = components['schemas']['Annotation'];
export type AnnotationCreateBody = components['schemas']['AnnotationCreate'];
export type AnnotationUpdateBody = components['schemas']['AnnotationUpdate'];

export type AnnotationListResult =
	{ ok: true; items: AnnotationRecord[] } | { ok: false; message: string };

export type AnnotationMutationResult =
	{ ok: true; item: AnnotationRecord } | { ok: false; message: string };

export type AnnotationDeleteResult = { ok: true } | { ok: false; message: string };

export type AnnotationApi = {
	list(slideId: string): Promise<AnnotationListResult>;
	create(slideId: string, body: AnnotationCreateBody): Promise<AnnotationMutationResult>;
	update(annotationId: string, body: AnnotationUpdateBody): Promise<AnnotationMutationResult>;
	remove(annotationId: string): Promise<AnnotationDeleteResult>;
};

const LOAD_ERROR = 'Annotations could not be loaded.';
const SAVE_ERROR = 'The annotation could not be saved.';
const UPDATE_ERROR = 'The annotation could not be updated.';
const DELETE_ERROR = 'The annotation could not be deleted.';

export function messageFromApiError(error: unknown, fallback: string): string {
	if (!error || typeof error !== 'object' || !('error' in error)) return fallback;
	const body = error.error;
	if (!body || typeof body !== 'object' || !('message' in body)) return fallback;
	if (typeof body.message !== 'string') return fallback;
	const message = body.message.trim();
	return message || fallback;
}

export async function listSlideAnnotations(slideId: string): Promise<AnnotationListResult> {
	try {
		const { data, error, response } = await api.GET('/api/slides/{slide_id}/annotations', {
			params: { path: { slide_id: slideId } }
		});
		if (!response.ok || !data)
			return { ok: false, message: messageFromApiError(error, LOAD_ERROR) };
		return { ok: true, items: data };
	} catch {
		return { ok: false, message: LOAD_ERROR };
	}
}

export async function createSlideAnnotation(
	slideId: string,
	body: AnnotationCreateBody
): Promise<AnnotationMutationResult> {
	try {
		const { data, error, response } = await api.POST('/api/slides/{slide_id}/annotations', {
			params: { path: { slide_id: slideId } },
			body
		});
		if (!response.ok || !data)
			return { ok: false, message: messageFromApiError(error, SAVE_ERROR) };
		return { ok: true, item: data };
	} catch {
		return { ok: false, message: SAVE_ERROR };
	}
}

export async function updateSlideAnnotation(
	annotationId: string,
	body: AnnotationUpdateBody
): Promise<AnnotationMutationResult> {
	try {
		const { data, error, response } = await api.PATCH('/api/annotations/{annotation_id}', {
			params: { path: { annotation_id: annotationId } },
			body
		});
		if (!response.ok || !data)
			return { ok: false, message: messageFromApiError(error, UPDATE_ERROR) };
		return { ok: true, item: data };
	} catch {
		return { ok: false, message: UPDATE_ERROR };
	}
}

export async function deleteSlideAnnotation(annotationId: string): Promise<AnnotationDeleteResult> {
	try {
		const { error, response } = await api.DELETE('/api/annotations/{annotation_id}', {
			params: { path: { annotation_id: annotationId } }
		});
		if (!response.ok) return { ok: false, message: messageFromApiError(error, DELETE_ERROR) };
		return { ok: true };
	} catch {
		return { ok: false, message: DELETE_ERROR };
	}
}

export const annotationApi: AnnotationApi = {
	list: listSlideAnnotations,
	create: createSlideAnnotation,
	update: updateSlideAnnotation,
	remove: deleteSlideAnnotation
};
