/**
 * Per-case evidence session. The panel is unmounted when another tab is open,
 * so the last query and its results live here for the rest of the page session.
 */

import {
	buildSearch,
	emptyFilters,
	isTextQuery,
	queryFromIntent,
	queryMode,
	querySupportsSlideScope,
	resultFooter,
	sameFilters,
	slideScopeUnavailableReason,
	visibleCaseHits,
	type ActiveQuery,
	type EvidenceFilters,
	type EvidenceIntent,
	type SearchFailure,
	type SearchMode,
	type SearchResponse,
	type SearchScope,
	type SlideScopeResponse
} from './evidence-model.js';
import { liveTransport, runEvidenceSearch, type EvidenceTransport } from './evidence-search.js';

type Listener = () => void;

let textQueriesStarted = 0;

export function claimFirstTextQuery(): boolean {
	textQueriesStarted += 1;
	return textQueriesStarted === 1;
}

export function resetTextQueryCount(): void {
	textQueriesStarted = 0;
}

export class EvidenceSession {
	readonly caseId: string;
	mode: SearchMode = 'tissue';
	draft = '';
	scope: SearchScope = 'corpus';
	filters: EvidenceFilters = emptyFilters();
	query: ActiveQuery | null = null;
	corpus: SearchResponse | null = null;
	regions: SlideScopeResponse | null = null;
	failure: SearchFailure | null = null;
	notice: string | null = null;
	searching = false;
	warming = false;
	consumedSeq = 0;
	scopeNote: string | null = null;

	#transport: EvidenceTransport;
	#warmupMs: number;
	#listeners = new Set<Listener>();
	#controller: AbortController | null = null;
	#token = 0;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#boundPatientId: string | null = null;

	constructor(caseId: string, options?: { transport?: EvidenceTransport; warmupMs?: number }) {
		this.caseId = caseId;
		this.#transport = options?.transport ?? liveTransport();
		this.#warmupMs = options?.warmupMs ?? 3000;
	}

	subscribe(listener: Listener): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	setMode(mode: SearchMode): void {
		if (this.mode === mode) return;
		this.mode = mode;
		this.#emit();
	}

	setDraft(draft: string): void {
		if (this.draft === draft) return;
		this.draft = draft;
		this.#emit();
	}

	get visibleHits() {
		return visibleCaseHits(this.corpus?.hits ?? [], this.caseId);
	}

	get footer(): string | null {
		if (this.regions) {
			return resultFooter(this.regions.patches.length, this.regions.took_ms, 'regions');
		}
		if (this.corpus) return resultFooter(this.visibleHits.length, this.corpus.took_ms, 'cases');
		return null;
	}

	get hasRows(): boolean {
		return this.visibleHits.length > 0 || (this.regions?.patches.length ?? 0) > 0;
	}

	get phase(): 'idle' | 'searching' | 'results' | 'empty' | 'error' | 'no-tissue' {
		if (this.failure?.kind === 'no-tissue') return 'no-tissue';
		if (this.failure) return 'error';
		if (this.searching) return 'searching';
		if (!this.query) return 'idle';
		if (this.hasRows) return 'results';
		if (this.corpus || this.regions) return 'empty';
		return 'idle';
	}

	async runIntent(intent: EvidenceIntent, seq: number, patientId: string | null): Promise<void> {
		if (seq === this.consumedSeq) return;
		this.consumedSeq = seq;
		const query = queryFromIntent(intent);
		this.mode = queryMode(query);
		if (query.kind === 'report-text' || query.kind === 'tissue-text') this.draft = query.text;
		this.scope = 'corpus';
		this.scopeNote = null;
		await this.#execute(query, patientId);
	}

	async submitText(patientId: string | null): Promise<void> {
		const text = this.draft.trim();
		if (!text) return;
		if (this.mode === 'reports') this.scope = 'corpus';
		const query: ActiveQuery =
			this.mode === 'reports' ? { kind: 'report-text', text } : { kind: 'tissue-text', text };
		await this.#execute(query, patientId);
	}

	/** Q3 on the open slide. Corpus scope: other signed-out cases, with their patches. */
	async casesLikeSlide(slideId: string, patientId: string | null): Promise<void> {
		if (!slideId) return;
		this.mode = 'tissue';
		this.scope = 'corpus';
		this.scopeNote = null;
		await this.#execute({ kind: 'slide', slideId }, patientId);
	}

	async setScope(next: SearchScope, patientId: string | null): Promise<void> {
		if (next === 'slide' && this.query && !querySupportsSlideScope(this.query)) {
			this.scopeNote = slideScopeUnavailableReason(this.query);
			this.#emit();
			return;
		}
		if (next === this.scope) return;
		this.scope = next;
		this.scopeNote = null;
		this.#emit();
		if (this.query) await this.#execute(this.query, patientId);
	}

	async setFilters(next: EvidenceFilters, patientId: string | null): Promise<void> {
		const filtersSame = sameFilters(this.filters, next);
		const patientSame = patientId === this.#boundPatientId;
		this.#boundPatientId = patientId;
		// Same-patient filtering needs the open case's patient, which can arrive after the toggle.
		if (filtersSame && (patientSame || !next.samePatient)) return;
		this.filters = { ...next };
		this.#emit();
		if (this.query && (!filtersSame || next.samePatient)) {
			await this.#execute(this.query, patientId);
		}
	}

	async retry(patientId: string | null): Promise<void> {
		if (this.query) await this.#execute(this.query, patientId);
	}

	clear(): void {
		this.#token += 1;
		this.#controller?.abort();
		this.#controller = null;
		this.#clearTimer();
		this.query = null;
		this.corpus = null;
		this.regions = null;
		this.failure = null;
		this.notice = null;
		this.searching = false;
		this.warming = false;
		this.scope = 'corpus';
		this.scopeNote = null;
		this.draft = '';
		this.#emit();
	}

	async #execute(query: ActiveQuery, patientId: string | null): Promise<void> {
		const built = buildSearch({
			query,
			scope: this.scope,
			filters: this.filters,
			contextCaseId: this.caseId,
			patientId
		});
		this.query = query;
		this.failure = null;
		if ('error' in built) {
			this.searching = false;
			this.warming = false;
			this.failure = { kind: 'error', message: built.error };
			this.#emit();
			return;
		}

		this.#controller?.abort();
		const controller = new AbortController();
		this.#controller = controller;
		const token = ++this.#token;
		this.searching = true;
		this.warming = false;
		this.#emit();

		const firstText = isTextQuery(query) ? claimFirstTextQuery() : false;
		this.#clearTimer();
		if (firstText) {
			this.#timer = setTimeout(() => {
				if (this.#token !== token || !this.searching) return;
				this.warming = true;
				this.#emit();
			}, this.#warmupMs);
		}

		try {
			const result = await runEvidenceSearch(this.#transport, built, controller.signal);
			if (this.#token !== token || controller.signal.aborted) return;
			if (!result.ok) {
				if (result.failure.message === 'cancelled') return;
				this.failure = result.failure;
				return;
			}
			this.corpus = result.corpus;
			this.regions = result.regions;
			this.notice = result.notice;
			this.failure = null;
		} catch {
			if (this.#token !== token || controller.signal.aborted) return;
			this.failure = { kind: 'error', message: 'The search failed.' };
		} finally {
			if (this.#token === token) {
				this.#clearTimer();
				this.searching = false;
				this.warming = false;
				this.#emit();
			}
		}
	}

	#clearTimer(): void {
		if (this.#timer != null) clearTimeout(this.#timer);
		this.#timer = null;
	}

	#emit(): void {
		for (const listener of this.#listeners) {
			listener();
		}
	}
}

const sessions = new Map<string, EvidenceSession>();

export function evidenceSessionFor(caseId: string, transport?: EvidenceTransport): EvidenceSession {
	const existing = sessions.get(caseId);
	if (existing) return existing;
	const session = new EvidenceSession(caseId, { transport });
	sessions.set(caseId, session);
	return session;
}

export function clearEvidenceSessions(): void {
	for (const session of sessions.values()) session.clear();
	sessions.clear();
	resetTextQueryCount();
}
