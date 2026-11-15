/**
 * Consult thread state. Counts shown on the ranking card come from
 * `PathologistRank.case_count` (the SQL rank_pathologists result), never from
 * counting names in the answer text.
 */

import {
	createFetchTransport,
	isAbortError,
	isAgentUnavailable,
	ConsultRequestError,
	type Citation,
	type ConsultMessage,
	type ConsultMessageCreate,
	type ConsultStreamEvent,
	type ConsultThread,
	type ConsultTransport,
	type MessageAttachments,
	type PathologistRank,
	type ToolTraceStep
} from './consult-stream.js';

export type {
	Citation,
	ConsultMessageCreate,
	ConsultStreamEvent,
	ConsultThread,
	ConsultTransport,
	MessageAttachments,
	PathologistRank,
	ToolTraceStep
};

type ConsultMessageStatus = ConsultMessage['status'];

export type ConsultViewStatus = ConsultMessageStatus | 'stopped';

export type ConsultRetry = {
	content: string;
	attachments: MessageAttachments | null;
};

export type ConsultViewMessage = {
	id: string;
	role: ConsultMessage['role'];
	content: string;
	attachments: MessageAttachments | null;
	citations: Citation[] | null;
	ranking: PathologistRank[] | null;
	steps: ToolTraceStep[];
	stepsOpen: boolean;
	status: ConsultViewStatus;
	error: string | null;
	retry: ConsultRetry | null;
};

export type ConsultPhase =
	'idle' | 'loading' | 'ready' | 'streaming' | 'load-error' | 'agent-unavailable';

export type ConsultSnapshot = {
	phase: ConsultPhase;
	caseId: string | null;
	threadId: string | null;
	messages: ConsultViewMessage[];
	loadError: string | null;
	unavailableMessage: string | null;
};

export const CONSULT_NOTICE =
	'The agent retrieves and summarises prior cases. It does not diagnose the open case.';

export const AGENT_UNAVAILABLE_TITLE = 'Consult agent unavailable';

export const AGENT_UNAVAILABLE_COPY =
	'The model provider cannot be reached. This case, the slides, and the other panels still work.';

export const CONSULT_STARTERS = [
	'Who should I consult on this case?',
	"Summarise this patient's previous cases",
	'Summarise similar cases',
	'What features distinguished similar cases?'
] as const;

const TOOL_TITLES: Record<string, string> = {
	get_case_context: 'Case context',
	get_patient_history: 'Patient history',
	search_patient_cases: "This patient's cases",
	search_similar_cases_by_morphology: 'Tissue search',
	search_patches_by_text: 'Morphology search',
	search_reports: 'Report search',
	get_report: 'Report',
	rank_pathologists: 'Pathologist ranking'
};

const controllers = new Map<string, ConsultController>();
let localSeq = 0;

export function starterQuestions(priorCaseCount: number): string[] {
	const [who, history, similar, features] = CONSULT_STARTERS;
	if (priorCaseCount > 0) return [history, who, similar, features];
	return [who, history, similar, features];
}

export function stepTitle(tool: string): string {
	return TOOL_TITLES[tool] ?? tool.replaceAll('_', ' ');
}

/** The number is the SQL `case_count`, not a count the model wrote. */
export function rankingCountLabel(rank: Pick<PathologistRank, 'case_count'>): string {
	return rank.case_count === 1 ? '1 relevant case' : `${rank.case_count} relevant cases`;
}

export function showRankingCard(ranking: readonly PathologistRank[] | null | undefined): boolean {
	return (ranking?.length ?? 0) > 0;
}

export function pathologistWorklistHref(pathologistId: string): string {
	const params = new URLSearchParams();
	params.set('assigned_to', pathologistId);
	params.set('status', 'signed_out');
	params.set('view', 'all');
	return `/?${params.toString()}`;
}

export function citationLabel(
	caseId: string,
	citations: readonly Citation[] | null | undefined
): string {
	const match = citations?.find((item) => item.case_id === caseId);
	const specimen = match?.case.specimen_label?.trim();
	return specimen || caseId;
}

export function uniqueCitations(citations: readonly Citation[] | null | undefined): Citation[] {
	if (!citations) return [];
	const seen = new Set<string>();
	const unique: Citation[] = [];
	for (const citation of citations) {
		if (seen.has(citation.case_id)) continue;
		seen.add(citation.case_id);
		unique.push(citation);
	}
	return unique;
}

export type RegionAttachmentInput = {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
	label?: string;
};

export function buildMessageAttachments(
	region: RegionAttachmentInput | null,
	caseIds: readonly string[] | null
): MessageAttachments | null {
	const ids = (caseIds ?? []).map((id) => id.trim()).filter((id) => id.length > 0);
	if (!region && ids.length === 0) return null;
	const attachments: MessageAttachments = {};
	if (region) {
		attachments.region = {
			slide_id: region.slideId,
			x: region.x,
			y: region.y,
			width: region.width,
			height: region.height
		};
	}
	if (ids.length > 0) attachments.case_ids = [...ids];
	return attachments;
}

export function regionChipLabel(region: {
	width: number;
	height: number;
	label?: string | null;
}): string {
	const label = region.label?.trim();
	if (label) return label;
	return `Region · ${Math.round(region.width)} × ${Math.round(region.height)} px`;
}

export function casesChipLabel(count: number): string {
	return count === 1 ? '1 case from evidence' : `${count} cases from evidence`;
}

export function idleConsultSnapshot(caseId: string | null = null): ConsultSnapshot {
	return {
		phase: 'idle',
		caseId,
		threadId: null,
		messages: [],
		loadError: null,
		unavailableMessage: null
	};
}

export function snapshotFromThread(thread: ConsultThread): ConsultSnapshot {
	const messages = thread.messages.map((message, index) => toView(message, thread.messages, index));
	const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');
	const unavailable =
		lastAssistant?.status === 'error' &&
		(isAgentUnavailable(null, lastAssistant.error) ||
			isAgentUnavailable(null, lastAssistant.content));
	return {
		phase: unavailable ? 'agent-unavailable' : 'ready',
		caseId: thread.case_id,
		threadId: thread.id,
		messages,
		loadError: null,
		unavailableMessage: unavailable ? 'The consult agent is unavailable.' : null
	};
}

export function reduceConsultEvent(
	message: ConsultViewMessage,
	event: ConsultStreamEvent
): ConsultViewMessage {
	switch (event.type) {
		case 'step':
			return {
				...message,
				stepsOpen: true,
				steps: [
					...message.steps,
					{ tool: event.tool, summary: event.summary, duration_ms: event.duration_ms }
				]
			};
		case 'text':
			return { ...message, content: message.content + event.content };
		case 'citations':
			return { ...message, citations: event.citations };
		case 'ranking':
			return { ...message, ranking: event.ranking };
		case 'done': {
			const saved = event.message;
			const failed = saved.status === 'error';
			return {
				...message,
				id: saved.id,
				content: saved.content,
				attachments: saved.attachments,
				citations: saved.citations,
				ranking: saved.ranking,
				steps: stepsOf(saved.tool_trace, message.steps),
				stepsOpen: false,
				status: failed ? 'error' : 'complete',
				error: failed ? saved.content.trim() || 'This answer failed.' : null,
				retry: failed ? message.retry : null
			};
		}
		case 'error':
			return {
				...message,
				content: message.content.trim() ? message.content : event.message,
				status: 'error',
				error: event.message,
				stepsOpen: true
			};
	}
}

export function consultControllerFor(caseId: string, userId: string): ConsultController {
	const key = `${caseId}\n${userId}`;
	const existing = controllers.get(key);
	if (existing) return existing;
	const created = new ConsultController(caseId, createFetchTransport());
	controllers.set(key, created);
	return created;
}

export class ConsultController {
	#snapshot: ConsultSnapshot;
	#transport: ConsultTransport;
	#listeners = new Set<(snapshot: ConsultSnapshot) => void>();
	#generation = 0;
	#abort: AbortController | null = null;
	#userStop = false;
	#loaded = false;
	#tail: Promise<void> = Promise.resolve();

	constructor(caseId: string, transport: ConsultTransport) {
		this.#snapshot = idleConsultSnapshot(caseId);
		this.#transport = transport;
	}

	get snapshot(): ConsultSnapshot {
		return this.#snapshot;
	}

	subscribe(listener: (snapshot: ConsultSnapshot) => void): () => void {
		this.#listeners.add(listener);
		listener(this.#snapshot);
		return () => {
			this.#listeners.delete(listener);
		};
	}

	/** Resolves when the latest send or reload finishes. */
	settled(): Promise<void> {
		return this.#tail;
	}

	ensureOpen(): Promise<void> {
		if (this.#loaded) return Promise.resolve();
		return this.#track(this.#load(false));
	}

	reload(): Promise<void> {
		this.#loaded = false;
		return this.#track(this.#load(false));
	}

	newThread(): Promise<void> {
		this.#loaded = false;
		return this.#track(this.#load(true));
	}

	beginSend(content: string, attachments: MessageAttachments | null): boolean {
		const text = content.trim();
		if (!this.#canSend(text)) return false;
		this.#tail = this.#send(text, attachments);
		return true;
	}

	stop(): void {
		if (this.#snapshot.phase !== 'streaming') return;
		this.#userStop = true;
		this.#abort?.abort();
	}

	retry(messageId: string): boolean {
		const message = this.#snapshot.messages.find((item) => item.id === messageId);
		if (!message?.retry || message.status !== 'error') return false;
		return this.beginSend(message.retry.content, message.retry.attachments);
	}

	toggleSteps(messageId: string): void {
		const message = this.#snapshot.messages.find((item) => item.id === messageId);
		if (!message || message.status === 'streaming') return;
		this.#set({
			...this.#snapshot,
			messages: this.#snapshot.messages.map((item) =>
				item.id === messageId ? { ...item, stepsOpen: !item.stepsOpen } : item
			)
		});
	}

	async #load(fresh: boolean): Promise<void> {
		const caseId = this.#snapshot.caseId;
		if (!caseId) return;
		const generation = ++this.#generation;
		this.#userStop = false;
		this.#abort?.abort();
		this.#abort = null;
		this.#set({
			...this.#snapshot,
			phase: 'loading',
			loadError: null,
			unavailableMessage: fresh ? null : this.#snapshot.unavailableMessage,
			threadId: fresh ? null : this.#snapshot.threadId,
			messages: fresh ? [] : this.#snapshot.messages
		});
		try {
			const started = await this.#transport.startThread(caseId, { new: fresh });
			if (generation !== this.#generation) return;
			let thread = started;
			try {
				thread = await this.#transport.getThread(started.id);
			} catch {
				thread = started;
			}
			if (generation !== this.#generation) return;
			this.#loaded = true;
			this.#set(snapshotFromThread(thread));
		} catch (error) {
			if (generation !== this.#generation) return;
			this.#loaded = false;
			this.#failLoad(error);
		}
	}

	async #send(text: string, attachments: MessageAttachments | null): Promise<void> {
		const threadId = this.#snapshot.threadId;
		if (!threadId) return;
		const generation = this.#generation;
		this.#userStop = false;
		const retry = { content: text, attachments };
		const user = viewMessage({
			id: localId('user'),
			role: 'user',
			content: text,
			attachments,
			status: 'complete'
		});
		const assistant = viewMessage({
			id: localId('assistant'),
			role: 'assistant',
			content: '',
			status: 'streaming',
			stepsOpen: true,
			retry
		});
		const abort = new AbortController();
		this.#abort = abort;
		this.#set({
			...this.#snapshot,
			phase: 'streaming',
			unavailableMessage: null,
			messages: [...this.#snapshot.messages, user, assistant]
		});
		const body: ConsultMessageCreate = attachments
			? { content: text, attachments }
			: { content: text };
		try {
			await this.#transport.streamMessage(threadId, body, abort.signal, (event) => {
				if (generation !== this.#generation) return;
				this.#apply(event);
			});
			if (generation !== this.#generation) return;
			this.#finishIfStillStreaming();
		} catch (error) {
			if (generation !== this.#generation) return;
			if (this.#userStop || isAbortError(error)) {
				this.#markStopped();
				return;
			}
			this.#markFailed(error);
		}
	}

	#apply(event: ConsultStreamEvent): void {
		const messages = this.#snapshot.messages.map((message, index, all) => {
			const streaming =
				index === all.length - 1 && message.role === 'assistant' && message.status === 'streaming';
			return streaming ? reduceConsultEvent(message, event) : message;
		});
		const last = messages.at(-1);
		let phase: ConsultPhase = this.#snapshot.phase;
		let unavailableMessage = this.#snapshot.unavailableMessage;
		if (event.type === 'error') {
			if (isAgentUnavailable(null, event.message)) {
				phase = 'agent-unavailable';
				unavailableMessage = event.message;
			} else {
				phase = 'ready';
				unavailableMessage = null;
			}
		} else if (event.type === 'done') {
			const failed = last?.status === 'error';
			if (failed && isAgentUnavailable(null, last?.error ?? last?.content)) {
				phase = 'agent-unavailable';
				unavailableMessage = 'The consult agent is unavailable.';
			} else {
				phase = 'ready';
				unavailableMessage = null;
			}
		}
		this.#set({ ...this.#snapshot, messages, phase, unavailableMessage });
	}

	#finishIfStillStreaming(): void {
		const last = this.#snapshot.messages.at(-1);
		if (!last || last.status !== 'streaming') {
			if (this.#snapshot.phase === 'streaming') this.#set({ ...this.#snapshot, phase: 'ready' });
			return;
		}
		this.#set({
			...this.#snapshot,
			phase: 'ready',
			messages: this.#snapshot.messages.map((message) =>
				message.id === last.id
					? {
							...message,
							status: 'error',
							error: 'The answer failed before it finished.',
							stepsOpen: true
						}
					: message
			)
		});
	}

	#markStopped(): void {
		this.#set({
			...this.#snapshot,
			phase: 'ready',
			messages: this.#snapshot.messages.map((message) =>
				message.status === 'streaming'
					? { ...message, status: 'stopped', error: null, retry: null, stepsOpen: true }
					: message
			)
		});
	}

	#markFailed(error: unknown): void {
		const failure = describeFailure(error);
		this.#set({
			...this.#snapshot,
			phase: failure.unavailable ? 'agent-unavailable' : 'ready',
			unavailableMessage: failure.unavailable ? failure.message : null,
			loadError: null,
			messages: this.#snapshot.messages.map((message) =>
				message.status === 'streaming'
					? {
							...message,
							status: 'error',
							error: failure.message,
							content: message.content.trim() ? message.content : failure.message,
							stepsOpen: true
						}
					: message
			)
		});
	}

	#failLoad(error: unknown): void {
		const failure = describeFailure(error);
		if (failure.unavailable) {
			this.#set({
				...this.#snapshot,
				phase: 'agent-unavailable',
				loadError: null,
				unavailableMessage: failure.message,
				messages: []
			});
			return;
		}
		this.#set({
			...this.#snapshot,
			phase: 'load-error',
			loadError: failure.message,
			unavailableMessage: null
		});
	}

	#canSend(text: string): boolean {
		return Boolean(
			text &&
			this.#snapshot.threadId &&
			this.#snapshot.phase !== 'streaming' &&
			this.#snapshot.phase !== 'loading' &&
			this.#snapshot.phase !== 'idle'
		);
	}

	#track(pending: Promise<void>): Promise<void> {
		this.#tail = pending;
		return pending;
	}

	#set(next: ConsultSnapshot): void {
		this.#snapshot = next;
		for (const listener of this.#listeners) listener(next);
	}
}

function toView(message: ConsultMessage, all: ConsultMessage[], index: number): ConsultViewMessage {
	const failed = message.role === 'assistant' && message.status === 'error';
	return viewMessage({
		id: message.id,
		role: message.role,
		content: message.content,
		attachments: message.attachments,
		citations: message.citations,
		ranking: message.ranking,
		steps: stepsOf(message.tool_trace, []),
		stepsOpen: message.status === 'streaming',
		status: message.status,
		error: failed ? message.content.trim() || 'This answer failed.' : null,
		retry: failed ? questionBefore(all, index) : null
	});
}

function viewMessage(
	message: Partial<ConsultViewMessage> &
		Pick<ConsultViewMessage, 'id' | 'role' | 'content' | 'status'>
): ConsultViewMessage {
	return {
		attachments: null,
		citations: null,
		ranking: null,
		steps: [],
		stepsOpen: false,
		error: null,
		retry: null,
		...message
	};
}

function questionBefore(messages: ConsultMessage[], index: number): ConsultRetry | null {
	for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
		const previous = messages[cursor];
		if (previous?.role === 'user') {
			return { content: previous.content, attachments: previous.attachments };
		}
	}
	return null;
}

function stepsOf(
	trace: ToolTraceStep[] | null | undefined,
	fallback: ToolTraceStep[]
): ToolTraceStep[] {
	if (!Array.isArray(trace)) return fallback;
	return trace.filter(
		(step) =>
			!!step &&
			typeof step.tool === 'string' &&
			typeof step.summary === 'string' &&
			typeof step.duration_ms === 'number'
	);
}

function localId(prefix: string): string {
	localSeq += 1;
	return `local-${prefix}-${localSeq}`;
}

function describeFailure(error: unknown): { message: string; unavailable: boolean } {
	if (error instanceof ConsultRequestError) {
		return { message: error.message, unavailable: error.unavailable };
	}
	if (isAbortError(error)) return { message: 'The answer was stopped.', unavailable: false };
	return { message: 'The answer failed. Try the same question again.', unavailable: false };
}
