import { describe, expect, test } from 'bun:test';
import {
	ConsultRequestError,
	type ConsultMessage,
	type ConsultStreamEvent,
	type ConsultThread,
	type ConsultTransport
} from './consult-stream.js';
import {
	AGENT_UNAVAILABLE_COPY,
	CONSULT_NOTICE,
	ConsultController,
	buildMessageAttachments,
	casesChipLabel,
	citationLabel,
	pathologistWorklistHref,
	rankingCountLabel,
	regionChipLabel,
	showRankingCard,
	starterQuestions,
	type ConsultSnapshot
} from './consult-state.js';

describe('consult copy and starters', () => {
	test('the notice says the agent retrieves precedent and does not diagnose', () => {
		expect(CONSULT_NOTICE).toContain('retrieves and summarises prior cases');
		expect(CONSULT_NOTICE).toContain('does not diagnose');
		expect(CONSULT_NOTICE.toLowerCase().includes('the diagnosis is')).toBe(false);
		expect(AGENT_UNAVAILABLE_COPY).toContain('other panels still work');
	});

	test('prior cases move the patient-history question to the front', () => {
		expect(starterQuestions(0)[0]).toBe('Who should I consult on this case?');
		expect(starterQuestions(2)).toEqual([
			"Summarise this patient's previous cases",
			'Who should I consult on this case?',
			'Summarise similar cases',
			'What features distinguished similar cases?'
		]);
	});
});

describe('consult ranking and citations', () => {
	test('the ranking label uses the SQL case_count and the worklist link is filtered', () => {
		const rank = {
			pathologist_id: 'path-adebayo',
			name: 'Dr Adebayo',
			specialty: 'breast' as const,
			case_count: 2,
			case_ids: ['breast-TCGA-A2-0001', 'breast-TCGA-A2-0003']
		};
		expect(rankingCountLabel(rank)).toBe('2 relevant cases');
		expect(rankingCountLabel({ case_count: 1 })).toBe('1 relevant case');
		expect(showRankingCard([rank])).toBe(true);
		expect(showRankingCard([])).toBe(false);
		expect(showRankingCard(null)).toBe(false);
		expect(pathologistWorklistHref('path-adebayo')).toBe(
			'/?assigned_to=path-adebayo&status=signed_out&view=all'
		);
		expect(citationLabel('breast-TCGA-A2-0001', [citation('breast-TCGA-A2-0001')])).toBe(
			'Left breast core'
		);
		expect(citationLabel('missing', null)).toBe('missing');
	});

	test('attachments use the API region and case_ids fields', () => {
		expect(
			buildMessageAttachments(
				{ slideId: 'slide-1', x: 10, y: 20, width: 30, height: 40, label: 'Selected region' },
				[' breast-TCGA-A2-0001 ', '']
			)
		).toEqual({
			region: { slide_id: 'slide-1', x: 10, y: 20, width: 30, height: 40 },
			case_ids: ['breast-TCGA-A2-0001']
		});
		expect(buildMessageAttachments(null, [])).toBeNull();
		expect(regionChipLabel({ width: 30.2, height: 40.6, label: 'Selected region' })).toBe(
			'Selected region'
		);
		expect(casesChipLabel(3)).toBe('3 cases from evidence');
	});
});

describe('consult session', () => {
	test('restores a thread with steps collapsed, then streams steps before the answer', async () => {
		const saved = assistantMessage({
			id: 'msg-answer',
			content: 'Precedent is in [case:breast-TCGA-A2-0001].',
			citations: [citation('breast-TCGA-A2-0001')],
			ranking: [rank()],
			tool_trace: [
				{ tool: 'search_reports', summary: 'Found 2 signed-out cases.', duration_ms: 4 },
				{ tool: 'rank_pathologists', summary: '1 pathologist, counted in SQL.', duration_ms: 2 }
			]
		});
		const thread = threadWith([userMessage('Who should I consult on this case?'), saved]);
		const script: ConsultStreamEvent[] = [
			{
				type: 'step',
				tool: 'search_similar_cases_by_morphology',
				summary: 'Found 2 cases by tissue.',
				duration_ms: 5
			},
			{
				type: 'step',
				tool: 'search_reports',
				summary: 'Found 2 signed-out cases.',
				duration_ms: 4
			},
			{ type: 'text', content: 'See ' },
			{ type: 'text', content: '[case:breast-TCGA-A2-0001].' },
			{ type: 'citations', citations: [citation('breast-TCGA-A2-0001')] },
			{ type: 'ranking', ranking: [rank()] },
			{ type: 'done', message: saved }
		];
		const seen: { afterSteps: ConsultSnapshot | null; afterFirstText: ConsultSnapshot | null } = {
			afterSteps: null,
			afterFirstText: null
		};
		const transport = scriptedTransport(thread, {
			async onStream(_body, onEvent) {
				onEvent(script[0]!);
				onEvent(script[1]!);
				seen.afterSteps = clone(transport.controller.snapshot);
				onEvent(script[2]!);
				seen.afterFirstText = clone(transport.controller.snapshot);
				for (const event of script.slice(3)) onEvent(event);
			}
		});
		const controller = new ConsultController('breast-TCGA-A2-0002', transport.transport);
		transport.controller = controller;
		await controller.ensureOpen();

		expect(transport.starts).toEqual([{ new: false }]);
		expect(transport.gets).toBe(1);
		const restored = controller.snapshot.messages[1];
		expect(restored?.stepsOpen).toBe(false);
		expect(restored?.steps).toHaveLength(2);
		expect(restored?.ranking?.[0]?.case_count).toBe(2);

		expect(controller.beginSend('Summarise similar cases', null)).toBe(true);
		await controller.settled();

		expect(seen.afterSteps?.phase).toBe('streaming');
		const mid = seen.afterSteps?.messages.at(-1);
		expect(mid?.steps.map((step) => step.summary)).toEqual([
			'Found 2 cases by tissue.',
			'Found 2 signed-out cases.'
		]);
		expect(mid?.content).toBe('');
		expect(mid?.stepsOpen).toBe(true);
		expect(seen.afterFirstText?.messages.at(-1)?.content).toBe('See ');
		expect(seen.afterFirstText?.messages.at(-1)?.steps).toHaveLength(2);

		const finished = controller.snapshot.messages.at(-1);
		expect(finished?.status).toBe('complete');
		expect(finished?.stepsOpen).toBe(false);
		expect(finished?.content).toContain('[case:breast-TCGA-A2-0001]');
		expect(finished?.citations?.[0]?.case_id).toBe('breast-TCGA-A2-0001');
		expect(finished?.ranking?.[0]?.case_count).toBe(2);
		expect(controller.snapshot.phase).toBe('ready');
		expect(controller.snapshot.messages[0]?.content).toBe('Who should I consult on this case?');
	});

	test('stop keeps the partial answer and an error leaves earlier messages', async () => {
		const thread = threadWith([
			userMessage('Who should I consult on this case?'),
			assistantMessage({ id: 'msg-old', content: 'Earlier precedent.', ranking: [rank()] })
		]);
		const captured: { signal: AbortSignal | null } = { signal: null };
		const transport = scriptedTransport(thread, {
			async onStream(_body, onEvent, nextSignal) {
				captured.signal = nextSignal;
				onEvent({
					type: 'step',
					tool: 'search_reports',
					summary: 'Found 1 signed-out case.',
					duration_ms: 1
				});
				onEvent({ type: 'text', content: 'Partial precedent' });
				await new Promise<void>((_resolve, reject) => {
					if (nextSignal.aborted) {
						reject(new DOMException('stopped', 'AbortError'));
						return;
					}
					nextSignal.addEventListener(
						'abort',
						() => reject(new DOMException('stopped', 'AbortError')),
						{ once: true }
					);
				});
			}
		});
		const controller = new ConsultController('breast-TCGA-A2-0002', transport.transport);
		await controller.ensureOpen();
		expect(controller.beginSend('What features distinguished similar cases?', null)).toBe(true);
		await Promise.resolve();
		expect(captured.signal?.aborted).toBe(false);
		controller.stop();
		await controller.settled();

		const stopped = controller.snapshot.messages.at(-1);
		expect(stopped?.status).toBe('stopped');
		expect(stopped?.content).toBe('Partial precedent');
		expect(stopped?.steps[0]?.summary).toBe('Found 1 signed-out case.');
		expect(controller.snapshot.phase).toBe('ready');
		expect(controller.snapshot.messages[1]?.content).toBe('Earlier precedent.');
		expect(controller.snapshot.messages[1]?.ranking?.[0]?.case_count).toBe(2);

		transport.onStream = async () => {
			throw new ConsultRequestError(422, 'The question could not be sent.');
		};
		expect(controller.retry('missing')).toBe(false);
		expect(controller.beginSend('Who should I consult on this case?', null)).toBe(true);
		await controller.settled();
		const failed = controller.snapshot.messages.at(-1);
		expect(failed?.status).toBe('error');
		expect(failed?.error).toBe('The question could not be sent.');
		expect(controller.snapshot.phase).toBe('ready');
		expect(controller.snapshot.unavailableMessage).toBeNull();
		expect(controller.snapshot.messages[1]?.status).toBe('complete');
		expect(controller.retry(failed?.id ?? '')).toBe(true);
	});

	test('503 and an unavailable error event keep the earlier thread and raise the banner', async () => {
		const thread = threadWith([
			userMessage('Hello'),
			assistantMessage({ id: 'msg-old', content: 'Kept.' })
		]);
		const transport = scriptedTransport(thread, {
			async onStream() {
				throw new ConsultRequestError(503, 'The consult agent is unavailable.');
			}
		});
		const controller = new ConsultController('breast-TCGA-A2-0002', transport.transport);
		await controller.ensureOpen();
		expect(controller.beginSend('Who should I consult on this case?', attachments())).toBe(true);
		await controller.settled();

		expect(controller.snapshot.phase).toBe('agent-unavailable');
		expect(controller.snapshot.unavailableMessage).toBe('The consult agent is unavailable.');
		expect(controller.snapshot.messages[1]?.content).toBe('Kept.');
		const failed = controller.snapshot.messages.at(-1);
		expect(failed?.status).toBe('error');
		expect(failed?.retry?.content).toBe('Who should I consult on this case?');
		expect(transport.bodies.at(-1)?.attachments?.case_ids).toEqual(['breast-TCGA-A2-0001']);
		expect(transport.bodies.at(-1)?.attachments?.region?.slide_id).toBe('slide-1');

		transport.onStream = async (_body, onEvent) => {
			onEvent({ type: 'text', content: 'Nothing further.' });
			onEvent({ type: 'error', message: 'The consult agent is unavailable.' });
		};
		expect(controller.beginSend('Summarise similar cases', null)).toBe(true);
		await controller.settled();
		expect(controller.snapshot.phase).toBe('agent-unavailable');
		expect(controller.snapshot.messages.at(-1)?.content).toBe('Nothing further.');
		expect(controller.snapshot.messages.at(-1)?.status).toBe('error');
		expect(controller.snapshot.messages[1]?.content).toBe('Kept.');
	});

	test('a new thread asks for a fresh conversation and replaces the one on screen', async () => {
		const thread = threadWith([userMessage('Old question')]);
		const transport = scriptedTransport(thread, { async onStream() {} });
		const controller = new ConsultController('breast-TCGA-A2-0002', transport.transport);
		await controller.ensureOpen();
		expect(controller.snapshot.messages).toHaveLength(1);
		await controller.newThread();
		expect(transport.starts).toEqual([{ new: false }, { new: true }]);
		expect(controller.snapshot.threadId).toBe('thread-fresh');
		expect(controller.snapshot.messages).toEqual([]);
		expect(controller.snapshot.phase).toBe('ready');
	});

	test('an empty ranking does not become a card and a declined answer is ordinary text', async () => {
		const thread = threadWith([]);
		const transport = scriptedTransport(thread, {
			async onStream(_body, onEvent) {
				onEvent({
					type: 'text',
					content: 'I cannot give a diagnosis. Similar cases concluded otherwise.'
				});
				onEvent({ type: 'ranking', ranking: [] });
				onEvent({
					type: 'done',
					message: assistantMessage({
						id: 'msg-decline',
						content: 'I cannot give a diagnosis. Similar cases concluded otherwise.',
						ranking: null
					})
				});
			}
		});
		const controller = new ConsultController('breast-TCGA-A2-0002', transport.transport);
		await controller.ensureOpen();
		expect(controller.beginSend('What is the diagnosis?', null)).toBe(true);
		await controller.settled();
		const answer = controller.snapshot.messages.at(-1);
		expect(answer?.status).toBe('complete');
		expect(showRankingCard(answer?.ranking)).toBe(false);
		expect(answer?.content).toContain('cannot give a diagnosis');
	});
});

function clone(snapshot: ConsultSnapshot): ConsultSnapshot {
	return structuredClone(snapshot);
}

function attachments() {
	return buildMessageAttachments({ slideId: 'slide-1', x: 1, y: 2, width: 3, height: 4 }, [
		'breast-TCGA-A2-0001'
	]);
}

function rank() {
	return {
		pathologist_id: 'path-adebayo',
		name: 'Dr Adebayo',
		specialty: 'breast' as const,
		case_count: 2,
		case_ids: ['breast-TCGA-A2-0001', 'breast-TCGA-A2-0003']
	};
}

function citation(caseId: string): NonNullable<ConsultMessage['citations']>[number] {
	return {
		case_id: caseId,
		slide_id: 'slide-cited',
		patch_id: null,
		quote: null,
		case: {
			id: caseId,
			accessioned_at: '2024-01-02T00:00:00Z',
			assigned_to: {
				id: 'path-adebayo',
				is_synthetic: true,
				name: 'Dr Adebayo',
				primary_specialty: 'breast'
			},
			conclusion_line: null,
			icd10: null,
			patient: {
				id: 'patient-a',
				display_label: 'Patient A',
				case_count: 2,
				is_synthetic_linkage: false,
				sex: 'F'
			},
			patient_age: 61,
			patient_sex: 'F',
			slide_count: 1,
			specialty: 'breast',
			specimen_label: 'Left breast core',
			status: 'signed_out',
			thumbnail_url: null
		}
	};
}

function userMessage(content: string): ConsultMessage {
	return {
		id: `user-${content.length}`,
		role: 'user',
		content,
		attachments: null,
		citations: null,
		ranking: null,
		tool_trace: null,
		status: 'complete',
		created_at: '2024-01-01T00:00:00Z'
	};
}

function assistantMessage(
	message: Partial<ConsultMessage> & Pick<ConsultMessage, 'id' | 'content'>
): ConsultMessage {
	return {
		role: 'assistant',
		attachments: null,
		citations: null,
		ranking: null,
		tool_trace: null,
		status: 'complete',
		created_at: '2024-01-01T00:01:00Z',
		...message
	};
}

function threadWith(messages: ConsultMessage[]): ConsultThread {
	return {
		id: 'thread-1',
		case_id: 'breast-TCGA-A2-0002',
		title: messages[0]?.content ?? null,
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-01T00:01:00Z',
		messages
	};
}

function scriptedTransport(
	initial: ConsultThread,
	handlers: {
		onStream: (
			body: { content: string },
			onEvent: (event: ConsultStreamEvent) => void,
			signal: AbortSignal
		) => Promise<void>;
	}
): {
	transport: ConsultTransport;
	starts: { new: boolean }[];
	gets: number;
	bodies: { content: string; attachments?: ConsultMessage['attachments'] }[];
	controller: ConsultController;
	onStream: (typeof handlers)['onStream'];
} {
	let thread = initial;
	const bag = {
		starts: [] as { new: boolean }[],
		gets: 0,
		bodies: [] as { content: string; attachments?: ConsultMessage['attachments'] }[],
		controller: null as unknown as ConsultController,
		onStream: handlers.onStream,
		transport: {} as ConsultTransport
	};
	bag.transport = {
		async startThread(_caseId, body) {
			bag.starts.push(body);
			if (body.new) {
				thread = { ...thread, id: 'thread-fresh', title: null, messages: [] };
			}
			return thread;
		},
		async getThread(threadId) {
			bag.gets += 1;
			if (thread.id !== threadId) throw new ConsultRequestError(404, 'Thread not found.');
			return thread;
		},
		async streamMessage(_threadId, body, signal, onEvent) {
			bag.bodies.push(body);
			await bag.onStream(body, onEvent, signal);
		}
	};
	return bag;
}
