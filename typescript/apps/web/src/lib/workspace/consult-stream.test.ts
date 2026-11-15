import { afterEach, describe, expect, test } from 'bun:test';
import { forgetActingUser, setActingUserId } from '#lib/identity/acting-user.js';
import {
	ConsultRequestError,
	createFetchTransport,
	createSseParser,
	parseSseBuffer,
	readEventStream,
	type ConsultStreamEvent
} from './consult-stream.js';

afterEach(() => {
	forgetActingUser();
});

const stepFrame =
	'event: step\ndata: {"duration_ms":3,"summary":"Found 2 signed-out cases.","tool":"search_reports","type":"step"}\n\n';
const textFrame =
	'event: text\ndata: {"content":"See [case:breast-TCGA-A2-0001].","type":"text"}\n\n';

describe('consult SSE parser', () => {
	test('emits a step before text, including when a frame is split across chunks', () => {
		const parser = createSseParser();
		const splitAt = stepFrame.indexOf('Found');
		const first = parser.push(stepFrame.slice(0, splitAt));
		expect(first).toEqual([]);
		const second = parser.push(stepFrame.slice(splitAt) + textFrame.slice(0, 8));
		expect(second.map((event) => event.type)).toEqual(['step']);
		const third = parser.push(textFrame.slice(8));
		expect(third).toEqual([{ type: 'text', content: 'See [case:breast-TCGA-A2-0001].' }]);
		expect(parser.finish()).toEqual([]);
	});

	test('accepts CRLF frames and ignores comments, malformed JSON, and unknown events', () => {
		const document = [
			': keep-alive',
			'',
			'event: step',
			'data: {"duration_ms":1,"summary":"Patient history.","tool":"get_patient_history","type":"step"}',
			'',
			'event: mystery',
			'data: {"type":"mystery"}',
			'',
			'event: text',
			'data: {not-json}',
			'',
			'event: text',
			'data: {"content":"Kept","type":"text"}',
			''
		].join('\r\n');
		expect(parseSseBuffer(document)).toEqual([
			{
				type: 'step',
				tool: 'get_patient_history',
				summary: 'Patient history.',
				duration_ms: 1
			},
			{ type: 'text', content: 'Kept' }
		]);
	});

	test('parses citations, ranking, done, and error payloads', () => {
		const events = parseSseBuffer(
			[
				'event: citations',
				'data: {"citations":[{"case_id":"breast-TCGA-A2-0001","case":{"id":"breast-TCGA-A2-0001"}}],"type":"citations"}',
				'',
				'event: ranking',
				'data: {"ranking":[{"case_count":2,"case_ids":["breast-TCGA-A2-0001","breast-TCGA-A2-0003"],"name":"Dr Adebayo","pathologist_id":"path-adebayo","specialty":"breast"}],"type":"ranking"}',
				'',
				'event: error',
				'data: {"message":"The consult agent is unavailable.","type":"error"}',
				'',
				'event: done',
				'data: {"message":{"content":"Done","id":"msg-1","role":"assistant","status":"complete"},"type":"done"}',
				''
			].join('\n')
		);
		expect(events.map((event) => event.type)).toEqual(['citations', 'ranking', 'error', 'done']);
		const ranking = events[1];
		expect(ranking?.type).toBe('ranking');
		if (ranking?.type === 'ranking') {
			expect(ranking.ranking[0]?.case_count).toBe(2);
			expect(ranking.ranking[0]?.case_ids).toEqual(['breast-TCGA-A2-0001', 'breast-TCGA-A2-0003']);
		}
	});

	test('drops a ranking entry whose specialty is not in the API enum', () => {
		const [event] = parseSseBuffer(
			'event: ranking\ndata: {"ranking":[{"case_count":1,"case_ids":["a"],"name":"No","pathologist_id":"p","specialty":"unknown"}],"type":"ranking"}\n\n'
		);
		expect(event).toEqual({ type: 'ranking', ranking: [] });
	});
});

describe('consult event stream reader', () => {
	test('reads chunked frames from a POST body', async () => {
		const encoder = new TextEncoder();
		const stream = new ReadableStream<Uint8Array>({
			start(controller) {
				controller.enqueue(encoder.encode(stepFrame.slice(0, 12)));
				controller.enqueue(encoder.encode(stepFrame.slice(12) + textFrame));
				controller.close();
			}
		});
		const events: ConsultStreamEvent[] = [];
		await readEventStream(stream, (event) => events.push(event));
		expect(events.map((event) => event.type)).toEqual(['step', 'text']);
	});

	test('abort keeps events already delivered and rejects the read', async () => {
		const encoder = new TextEncoder();
		const stream = new ReadableStream<Uint8Array>({
			pull(controller) {
				controller.enqueue(
					encoder.encode('event: text\ndata: {"content":"Partial","type":"text"}\n\n')
				);
			}
		});
		const events: ConsultStreamEvent[] = [];
		const abort = new AbortController();
		const pending = readEventStream(
			stream,
			(event) => {
				events.push(event);
				abort.abort();
			},
			abort.signal
		);
		let thrown = '';
		try {
			await pending;
		} catch (error) {
			thrown = error instanceof Error ? error.message : '';
		}
		expect(thrown).toContain('stopped');
		expect(events).toEqual([{ type: 'text', content: 'Partial' }]);
	});
});

describe('consult fetch transport', () => {
	test('sends X-User-Id and the attachment body on the message POST', async () => {
		setActingUserId('path-okafor');
		const requests: { url: string; init: RequestInit | undefined }[] = [];
		const transport = createFetchTransport(async (input, init) => {
			requests.push({ url: String(input), init });
			const method = init?.method ?? 'GET';
			if (method === 'GET' || String(input).endsWith('/consult/threads')) {
				return Response.json(threadPayload());
			}
			const encoder = new TextEncoder();
			return new Response(
				new ReadableStream({
					start(controller) {
						controller.enqueue(encoder.encode(textFrame));
						controller.close();
					}
				}),
				{ status: 200, headers: { 'content-type': 'text/event-stream' } }
			);
		});

		const started = await transport.startThread('breast-TCGA-A2-0002', { new: false });
		expect(started.id).toBe('thread-1');
		const events: ConsultStreamEvent[] = [];
		await transport.streamMessage(
			'thread-1',
			{
				content: 'Who should I consult on this case?',
				attachments: {
					region: { slide_id: 'slide-1', x: 1, y: 2, width: 3, height: 4 },
					case_ids: ['breast-TCGA-A2-0001']
				}
			},
			new AbortController().signal,
			(event) => events.push(event)
		);

		const start = requests[0];
		expect(start?.url).toBe('/api/cases/breast-TCGA-A2-0002/consult/threads');
		expect(start?.init?.method).toBe('POST');
		expect(new Headers(start?.init?.headers).get('X-User-Id')).toBe('path-okafor');
		expect(JSON.parse(String(start?.init?.body))).toEqual({ new: false });
		const message = requests[1];
		expect(message?.url).toBe('/api/consult/threads/thread-1/messages');
		expect(message?.init?.method).toBe('POST');
		const messageHeaders = new Headers(message?.init?.headers);
		expect(messageHeaders.get('X-User-Id')).toBe('path-okafor');
		expect(messageHeaders.get('Accept')).toBe('text/event-stream');
		expect(JSON.parse(String(message?.init?.body))).toEqual({
			content: 'Who should I consult on this case?',
			attachments: {
				region: { slide_id: 'slide-1', x: 1, y: 2, width: 3, height: 4 },
				case_ids: ['breast-TCGA-A2-0001']
			}
		});
		expect(events.map((event) => event.type)).toEqual(['text']);
	});

	test('a 503 response is an agent-unavailable error', async () => {
		const transport = createFetchTransport(async () =>
			Response.json({ error: { code: 'unavailable', message: 'upstream down' } }, { status: 503 })
		);
		const error = await transport
			.streamMessage(
				'thread-1',
				{ content: 'Hello' },
				new AbortController().signal,
				() => undefined
			)
			.catch((caught: unknown) => caught);
		expect(error instanceof ConsultRequestError).toBe(true);
		if (error instanceof ConsultRequestError) {
			expect(error.status).toBe(503);
			expect(error.unavailable).toBe(true);
			expect(error.message).toBe('The consult agent is unavailable.');
		}
	});
});

function threadPayload() {
	return {
		id: 'thread-1',
		case_id: 'breast-TCGA-A2-0002',
		title: null,
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-01T00:00:00Z',
		messages: []
	};
}
