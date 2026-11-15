/**
 * POST server-sent events for the consult agent.
 * The browser EventSource API cannot send a JSON body, so the panel reads
 * `fetch` + a stream reader. Model output is data, never HTML.
 */

import { ACTING_USER_HEADER, getActingUserId } from '#lib/identity/acting-user.js';
import type { components } from '#lib/api/schema.js';

export type ConsultStreamEvent =
	| components['schemas']['StepEvent']
	| components['schemas']['TextEvent']
	| components['schemas']['CitationsEvent']
	| components['schemas']['RankingEvent']
	| components['schemas']['DoneEvent']
	| components['schemas']['ErrorEvent'];

export type ConsultThread = components['schemas']['ConsultThread'];
export type ConsultMessage = components['schemas']['ConsultMessage'];
export type ConsultMessageCreate = components['schemas']['ConsultMessageCreate'];
export type Citation = components['schemas']['Citation'];
export type PathologistRank = components['schemas']['PathologistRank'];
export type ToolTraceStep = components['schemas']['ToolTraceStep'];
export type MessageAttachments = components['schemas']['MessageAttachments'];
type Specialty = components['schemas']['Specialty'];

export interface ConsultTransport {
	startThread(caseId: string, body: { new: boolean }): Promise<ConsultThread>;
	getThread(threadId: string): Promise<ConsultThread>;
	streamMessage(
		threadId: string,
		body: ConsultMessageCreate,
		signal: AbortSignal,
		onEvent: (event: ConsultStreamEvent) => void
	): Promise<void>;
}

const SPECIALTIES = new Set<Specialty>([
	'breast',
	'thorax',
	'colorectal',
	'gastrointestinal',
	'hematologic',
	'skin'
]);

export function isAgentUnavailable(
	status: number | null,
	message: string | null | undefined
): boolean {
	if (status === 503) return true;
	return typeof message === 'string' && message.toLowerCase().includes('unavailable');
}

export class ConsultRequestError extends Error {
	readonly status: number;
	readonly unavailable: boolean;

	constructor(status: number, message: string) {
		super(message);
		this.name = 'ConsultRequestError';
		this.status = status;
		this.unavailable = isAgentUnavailable(status, message);
	}
}

export function isAbortError(error: unknown): boolean {
	return (
		(error instanceof DOMException && error.name === 'AbortError') ||
		(error instanceof Error && error.name === 'AbortError')
	);
}

export function createSseParser(): {
	push(chunk: string): ConsultStreamEvent[];
	finish(): ConsultStreamEvent[];
} {
	let buffer = '';
	return {
		push(chunk: string): ConsultStreamEvent[] {
			buffer += chunk;
			const parts = buffer.split(/\r?\n\r?\n/);
			buffer = parts.pop() ?? '';
			return frames(parts);
		},
		finish(): ConsultStreamEvent[] {
			const tail = buffer;
			buffer = '';
			if (!tail.trim()) return [];
			return frames([tail]);
		}
	};
}

/** Parse a complete SSE document. Incomplete trailing frames are flushed. */
export function parseSseBuffer(text: string): ConsultStreamEvent[] {
	const parser = createSseParser();
	return [...parser.push(text), ...parser.finish()];
}

export async function readEventStream(
	body: ReadableStream<Uint8Array>,
	onEvent: (event: ConsultStreamEvent) => void,
	signal?: AbortSignal
): Promise<void> {
	if (signal?.aborted) throw abortError();
	const reader = body.getReader();
	const abort = () => {
		void reader.cancel().catch(() => undefined);
	};
	signal?.addEventListener('abort', abort, { once: true });
	const decoder = new TextDecoder();
	const parser = createSseParser();
	try {
		while (true) {
			if (signal?.aborted) throw abortError();
			const { done, value } = await reader.read();
			if (signal?.aborted) throw abortError();
			if (done) break;
			for (const event of parser.push(decoder.decode(value, { stream: true }))) onEvent(event);
		}
		for (const event of parser.push(decoder.decode())) onEvent(event);
		for (const event of parser.finish()) onEvent(event);
	} catch (error) {
		if (signal?.aborted || isAbortError(error)) throw abortError();
		throw error;
	} finally {
		signal?.removeEventListener('abort', abort);
		try {
			reader.releaseLock();
		} catch {
			// cancel() already released the reader.
		}
	}
}

export function createFetchTransport(fetchImpl: typeof fetch = globalThis.fetch): ConsultTransport {
	return {
		startThread(caseId, body) {
			return requestThread(fetchImpl, `/api/cases/${encodeURIComponent(caseId)}/consult/threads`, {
				method: 'POST',
				headers: jsonHeaders(),
				body: JSON.stringify({ new: body.new })
			});
		},
		getThread(threadId) {
			return requestThread(fetchImpl, `/api/consult/threads/${encodeURIComponent(threadId)}`, {
				method: 'GET',
				headers: jsonHeaders()
			});
		},
		async streamMessage(threadId, body, signal, onEvent) {
			const headers = jsonHeaders();
			headers.set('Accept', 'text/event-stream');
			const response = await fetchImpl(
				`/api/consult/threads/${encodeURIComponent(threadId)}/messages`,
				{
					method: 'POST',
					headers,
					body: JSON.stringify(body),
					signal
				}
			);
			if (!response.ok) throw await toRequestError(response);
			if (!response.body) {
				throw new ConsultRequestError(response.status, 'The consult stream was empty.');
			}
			await readEventStream(response.body, onEvent, signal);
		}
	};
}

function jsonHeaders(): Headers {
	const headers = new Headers({
		Accept: 'application/json',
		'Content-Type': 'application/json'
	});
	const userId = getActingUserId();
	if (userId) headers.set(ACTING_USER_HEADER, userId);
	return headers;
}

async function requestThread(
	fetchImpl: typeof fetch,
	url: string,
	init: RequestInit
): Promise<ConsultThread> {
	const response = await fetchImpl(url, init);
	if (!response.ok) throw await toRequestError(response);
	return asThread(await response.json());
}

async function toRequestError(response: Response): Promise<ConsultRequestError> {
	let message = `The consult request failed (${response.status}).`;
	try {
		const payload: unknown = await response.json();
		if (isRecord(payload) && isRecord(payload.error) && typeof payload.error.message === 'string') {
			message = payload.error.message;
		}
	} catch {
		// A non-JSON error still carries the status.
	}
	if (response.status === 503 && !isAgentUnavailable(null, message)) {
		message = 'The consult agent is unavailable.';
	}
	return new ConsultRequestError(response.status, message);
}

function frames(parts: string[]): ConsultStreamEvent[] {
	const events: ConsultStreamEvent[] = [];
	for (const part of parts) {
		const event = parseFrame(part);
		if (event) events.push(event);
	}
	return events;
}

function parseFrame(frame: string): ConsultStreamEvent | null {
	let eventName = '';
	const data: string[] = [];
	for (const rawLine of frame.split(/\r?\n/)) {
		const line = rawLine.trimEnd();
		if (!line || line.startsWith(':')) continue;
		if (line.startsWith('event:')) {
			eventName = line.slice('event:'.length).trim();
			continue;
		}
		if (line.startsWith('data:')) {
			data.push(line.slice('data:'.length).replace(/^ /, ''));
		}
	}
	if (data.length === 0) return null;
	try {
		return asStreamEvent(JSON.parse(data.join('\n')), eventName);
	} catch {
		return null;
	}
}

function asStreamEvent(value: unknown, eventName: string): ConsultStreamEvent | null {
	if (!isRecord(value)) return null;
	const type = typeof value.type === 'string' ? value.type : eventName;
	if (type === 'step') {
		if (typeof value.tool !== 'string' || typeof value.summary !== 'string') return null;
		if (typeof value.duration_ms !== 'number' || !Number.isFinite(value.duration_ms)) return null;
		return {
			type: 'step',
			tool: value.tool,
			summary: value.summary,
			duration_ms: value.duration_ms
		};
	}
	if (type === 'text') {
		if (typeof value.content !== 'string') return null;
		return { type: 'text', content: value.content };
	}
	if (type === 'citations') {
		if (!Array.isArray(value.citations)) return null;
		const citations = value.citations
			.map(asCitation)
			.filter((item): item is Citation => item !== null);
		return { type: 'citations', citations };
	}
	if (type === 'ranking') {
		if (!Array.isArray(value.ranking)) return null;
		const ranking = value.ranking
			.map(asRank)
			.filter((item): item is PathologistRank => item !== null);
		return { type: 'ranking', ranking };
	}
	if (type === 'done') {
		const message = asMessage(value.message);
		if (!message) return null;
		return { type: 'done', message };
	}
	if (type === 'error') {
		if (typeof value.message !== 'string') return null;
		return { type: 'error', message: value.message };
	}
	return null;
}

function asCitation(value: unknown): Citation | null {
	if (!isRecord(value) || typeof value.case_id !== 'string' || !isRecord(value.case)) return null;
	if (typeof value.case.id !== 'string') return null;
	return value as Citation;
}

function asRank(value: unknown): PathologistRank | null {
	if (!isRecord(value)) return null;
	if (typeof value.pathologist_id !== 'string' || typeof value.name !== 'string') return null;
	if (typeof value.specialty !== 'string' || !SPECIALTIES.has(value.specialty as Specialty))
		return null;
	if (typeof value.case_count !== 'number' || !Number.isFinite(value.case_count)) return null;
	if (!Array.isArray(value.case_ids) || !value.case_ids.every((id) => typeof id === 'string'))
		return null;
	return {
		pathologist_id: value.pathologist_id,
		name: value.name,
		specialty: value.specialty as Specialty,
		case_count: value.case_count,
		case_ids: value.case_ids
	};
}

function asMessage(value: unknown): ConsultMessage | null {
	if (!isRecord(value)) return null;
	if (typeof value.id !== 'string' || typeof value.content !== 'string') return null;
	if (value.role !== 'user' && value.role !== 'assistant') return null;
	if (value.status !== 'complete' && value.status !== 'streaming' && value.status !== 'error')
		return null;
	return value as ConsultMessage;
}

function asThread(value: unknown): ConsultThread {
	if (!isRecord(value) || typeof value.id !== 'string' || !Array.isArray(value.messages)) {
		throw new ConsultRequestError(500, 'The consult thread could not be read.');
	}
	if (typeof value.case_id !== 'string') {
		throw new ConsultRequestError(500, 'The consult thread could not be read.');
	}
	return value as ConsultThread;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function abortError(): DOMException {
	return new DOMException('The answer was stopped.', 'AbortError');
}
