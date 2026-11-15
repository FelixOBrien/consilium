import { api } from '#lib/api/client.js';
import { normalisePatches, type HeatmapPatchScore } from './heatmap-ramp.js';

export type HeatmapLoad =
	| { kind: 'ok'; text: string; patches: HeatmapPatchScore[] }
	| { kind: 'error'; message: string }
	| { kind: 'aborted' };

const FAILURE = 'Similarity could not be computed.';

/** Body for F-06. `text` alone — never `concept_id` or `negative_text`. */
export function heatmapTextBody(text: string): { text: string } {
	return { text };
}

/**
 * Score the open slide against one report word.
 * An aborted request is not an error: the previous overlay stays up until a newer response lands.
 */
export async function loadSlideHeatmap(
	slideId: string,
	text: string,
	signal?: AbortSignal
): Promise<HeatmapLoad> {
	if (signal?.aborted) return { kind: 'aborted' };
	try {
		const result = await api.POST('/api/slides/{slide_id}/heatmap', {
			params: { path: { slide_id: slideId } },
			body: heatmapTextBody(text),
			signal
		});
		if (signal?.aborted) return { kind: 'aborted' };
		if (!result.response.ok || !result.data) {
			return { kind: 'error', message: messageFrom(result.error, result.response.status) };
		}
		return {
			kind: 'ok',
			text: result.data.text,
			patches: normalisePatches(result.data.patches)
		};
	} catch (error) {
		if (signal?.aborted || isAbortError(error)) return { kind: 'aborted' };
		return { kind: 'error', message: FAILURE };
	}
}

function messageFrom(payload: unknown, status: number): string {
	if (payload && typeof payload === 'object' && 'error' in payload) {
		const error = payload.error;
		if (
			error &&
			typeof error === 'object' &&
			'message' in error &&
			typeof error.message === 'string' &&
			error.message.trim()
		) {
			return error.message.trim();
		}
	}
	if (status === 404) return 'This slide has no similarity map.';
	return FAILURE;
}

function isAbortError(error: unknown): boolean {
	return (
		(error instanceof DOMException && error.name === 'AbortError') ||
		(error instanceof Error && error.name === 'AbortError')
	);
}
