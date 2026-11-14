import type { ViewerAnnotationShape } from './overlay-layers.js';
import {
	annotationApi,
	type AnnotationApi,
	type AnnotationCreateBody,
	type AnnotationRecord
} from './annotations-api.js';
import {
	ANNOTATION_LABEL_MAX,
	annotationIsOwn,
	draftViewerShape,
	flyTarget,
	formatAnnotationTime,
	kindLabel,
	notePreview,
	regionHandoff,
	roundDrawn,
	roundRect,
	sortNewestFirst,
	toViewerShape,
	type AnnotationLike,
	type DrawnGeometry,
	type Level0Point,
	type Level0Rect,
	type SlideBounds
} from './annotations-geometry.js';

export type SelectionRegion = {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
	seq: number;
};

export type RegionQuery = {
	slideId: string;
	x: number;
	y: number;
	width: number;
	height: number;
};

export type AnnotationHost = {
	setAnnotationShapes(shapes: ViewerAnnotationShape[]): void;
	setDraft(shape: ViewerAnnotationShape | null): void;
	startAnnotationDraw(
		kind: 'rect' | 'point',
		onComplete: (geom: DrawnGeometry) => void,
		onCancel?: () => void
	): void;
	cancelInteractionMode(): void;
	flyToLevel0(target: RegionQuery): void;
	triggerEvidenceSearch(region: RegionQuery): void;
	attachToConsult(region: RegionQuery & { label?: string }): void;
	getBounds(): SlideBounds | null;
};

type Draft = {
	phase: 'drawing' | 'form' | 'saving';
	kind: 'rect' | 'point';
	geometry: Level0Rect | Level0Point | null;
	label: string;
	note: string;
	error: string | null;
	source: 'tool' | 'selection';
};

export type AnnotationRow = {
	id: string;
	label: string;
	noteStart: string | null;
	kind: 'rect' | 'point';
	kindLabel: 'Rectangle' | 'Point';
	authorName: string;
	synthetic: boolean;
	createdAt: string;
	timeLabel: string;
	isOwn: boolean;
	selected: boolean;
	rect: boolean;
};

export type AnnotationsSnapshot = {
	phase: 'idle' | 'loading' | 'ready' | 'error';
	loadError: string | null;
	items: AnnotationRow[];
	selectedId: string | null;
	draft: Draft | null;
	editingId: string | null;
	editLabel: string;
	editNote: string;
	editError: string | null;
	editSaving: boolean;
	confirmDeleteId: string | null;
	deleteError: string | null;
	deleting: boolean;
	focusRequest: { id: string; nonce: number } | null;
};

const sessions = new WeakMap<object, AnnotationsSession>();

export function sharedAnnotationsSession(
	key: object,
	create: () => AnnotationsSession
): AnnotationsSession {
	const existing = sessions.get(key);
	if (existing) return existing;
	const session = create();
	sessions.set(key, session);
	return session;
}

export class AnnotationsSession {
	#client: AnnotationApi;
	#host: AnnotationHost;
	#listeners = new Set<() => void>();
	#slideId: string | null = null;
	#meId: string | null = null;
	#items: AnnotationRecord[] = [];
	#phase: AnnotationsSnapshot['phase'] = 'idle';
	#loadError: string | null = null;
	#selectedId: string | null = null;
	#draft: Draft | null = null;
	#editingId: string | null = null;
	#editLabel = '';
	#editNote = '';
	#editError: string | null = null;
	#editSaving = false;
	#confirmDeleteId: string | null = null;
	#deleteError: string | null = null;
	#deleting = false;
	#focusRequest: { id: string; nonce: number } | null = null;
	#focusNonce = 0;
	#appliedSeq = 0;
	#token = 0;
	#saveToken = 0;
	#fetchKey = '';
	#inflightKey = '';
	#inflight: Promise<void> | null = null;

	constructor(host: AnnotationHost, client: AnnotationApi = annotationApi) {
		this.#client = client;
		this.#host = host;
	}

	subscribe(listener: () => void): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	snapshot(): AnnotationsSnapshot {
		const selectedId = this.#selectedId;
		return {
			phase: this.#phase,
			loadError: this.#loadError,
			items: this.#items.map((item) => this.#row(item, selectedId)),
			selectedId,
			draft: this.#draft ? { ...this.#draft, geometry: this.#draft.geometry } : null,
			editingId: this.#editingId,
			editLabel: this.#editLabel,
			editNote: this.#editNote,
			editError: this.#editError,
			editSaving: this.#editSaving,
			confirmDeleteId: this.#confirmDeleteId,
			deleteError: this.#deleteError,
			deleting: this.#deleting,
			focusRequest: this.#focusRequest
		};
	}

	sync(slideId: string | null, meId: string | null): Promise<void> {
		const slideChanged = slideId !== this.#slideId;
		const actorChanged = meId !== this.#meId;
		const previousSlide = this.#slideId;
		this.#meId = meId;
		if (slideChanged) {
			this.#slideId = slideId;
			this.#items = [];
			this.#selectedId = null;
			this.#editingId = null;
			this.#editSaving = false;
			this.#confirmDeleteId = null;
			this.#deleteError = null;
			this.#deleting = false;
			this.#loadError = null;
			this.#saveToken += 1;
			this.#draft = null;
			if (previousSlide) {
				this.#host.cancelInteractionMode();
				this.#host.setDraft(null);
			}
			this.#phase = slideId ? 'loading' : 'idle';
			this.#publishShapes();
			this.#emit();
		} else if (actorChanged) {
			this.#publishShapes();
			this.#emit();
		}
		if (!slideId) return Promise.resolve();
		const key = this.#key();
		if (
			!slideChanged &&
			!actorChanged &&
			(this.#fetchKey === key || this.#inflightKey === key) &&
			(this.#phase === 'ready' || this.#phase === 'loading')
		) {
			return this.#inflight ?? Promise.resolve();
		}
		return this.#fetch(slideId, key);
	}

	reload(): Promise<void> {
		if (!this.#slideId) return Promise.resolve();
		this.#fetchKey = '';
		this.#inflightKey = '';
		this.#phase = 'loading';
		this.#loadError = null;
		this.#publishShapes();
		this.#emit();
		return this.#fetch(this.#slideId, this.#key());
	}

	startDraw(kind: 'rect' | 'point'): void {
		if (this.#draft?.phase === 'saving' || this.#editSaving) return;
		this.#host.startAnnotationDraw(
			kind,
			(geom) => this.#finishDraw(geom),
			() => this.#drawCancelled()
		);
		this.#editingId = null;
		this.#confirmDeleteId = null;
		this.#draft = {
			phase: 'drawing',
			kind,
			geometry: null,
			label: '',
			note: '',
			error: null,
			source: 'tool'
		};
		this.#emit();
	}

	/** Drop an unsaved mark. Drawing mode ends through `cancelInteractionMode`. */
	cancel(): void {
		if (!this.#draft || this.#draft.phase === 'saving') return;
		this.#saveToken += 1;
		this.#draft = null;
		this.#host.cancelInteractionMode();
		this.#host.setDraft(null);
		this.#emit();
	}

	offerSelection(region: SelectionRegion, activeSlideId: string | null): void {
		if (!activeSlideId || region.slideId !== activeSlideId) return;
		if (region.seq === this.#appliedSeq) return;
		if (this.#draft?.phase === 'saving') return;
		this.#appliedSeq = region.seq;
		if (this.#draft?.phase === 'drawing') this.#host.cancelInteractionMode();
		const rounded = roundRect(
			{ x: region.x, y: region.y, w: region.width, h: region.height },
			this.#host.getBounds()
		);
		this.#editingId = null;
		this.#confirmDeleteId = null;
		this.#draft = {
			phase: 'form',
			kind: 'rect',
			geometry: rounded.ok ? rounded.geometry : null,
			label: '',
			note: '',
			error: rounded.ok ? null : rounded.message,
			source: 'selection'
		};
		this.#publishShapes();
		this.#emit();
	}

	setDraftLabel(label: string): void {
		if (!this.#draft || this.#draft.phase !== 'form') return;
		if (this.#draft.label === label) return;
		this.#draft = { ...this.#draft, label, error: null };
		this.#publishShapes();
		this.#emit();
	}

	setDraftNote(note: string): void {
		if (!this.#draft || this.#draft.phase !== 'form') return;
		if (this.#draft.note === note) return;
		this.#draft = { ...this.#draft, note };
		this.#emit();
	}

	async save(): Promise<void> {
		const draft = this.#draft;
		const slideId = this.#slideId;
		if (!draft || draft.phase === 'drawing' || !slideId) return;
		const labelError = labelProblem(draft.label);
		if (labelError || !draft.geometry) {
			this.#draft = {
				...draft,
				phase: 'form',
				error: labelError ?? draft.error ?? 'Draw a mark first.'
			};
			this.#emit();
			return;
		}
		const body = createBody(draft.kind, draft.geometry, draft.label, draft.note);
		if (!body) {
			this.#draft = { ...draft, phase: 'form', error: 'That mark could not be saved.' };
			this.#emit();
			return;
		}
		const token = ++this.#saveToken;
		this.#draft = { ...draft, phase: 'saving', error: null };
		this.#emit();
		const result = await this.#client.create(slideId, body);
		if (token !== this.#saveToken || this.#slideId !== slideId) return;
		if (!result.ok) {
			this.#draft = { ...draft, phase: 'form', error: result.message };
			this.#publishShapes();
			this.#emit();
			return;
		}
		const listWasReady = this.#phase === 'ready' && this.#fetchKey === this.#key();
		this.#dropInflightList();
		this.#items = sortNewestFirst([
			result.item,
			...this.#items.filter((item) => item.id !== result.item.id)
		]);
		this.#selectedId = result.item.id;
		this.#draft = null;
		this.#phase = 'ready';
		this.#loadError = null;
		this.#publishShapes();
		this.#emit();
		if (!listWasReady) await this.#fetch(slideId, this.#key());
	}

	highlight(id: string, focus: boolean): void {
		this.#selectedId = id;
		if (focus) this.#focusRequest = { id, nonce: ++this.#focusNonce };
		this.#publishShapes();
		this.#emit();
	}

	goTo(id: string): void {
		const item = this.#find(id);
		if (!item) return;
		this.#selectedId = id;
		this.#publishShapes();
		this.#emit();
		this.#host.flyToLevel0(flyTarget(asLike(item)));
	}

	findSimilar(id: string): void {
		const item = this.#find(id);
		if (!item) return;
		const region = regionHandoff(asLike(item));
		if (!region) return;
		this.#host.triggerEvidenceSearch(region);
	}

	ask(id: string): void {
		const item = this.#find(id);
		if (!item) return;
		const region = regionHandoff(asLike(item));
		if (!region) return;
		this.#host.attachToConsult({ ...region, label: item.label });
	}

	beginEdit(id: string): void {
		if (this.#draft || this.#editSaving) return;
		const item = this.#find(id);
		if (!item || !annotationIsOwn(asLike(item), this.#meId)) return;
		this.#editingId = id;
		this.#editLabel = item.label;
		this.#editNote = item.note ?? '';
		this.#editError = null;
		this.#confirmDeleteId = null;
		this.#emit();
	}

	setEditLabel(label: string): void {
		if (!this.#editingId || this.#editSaving) return;
		this.#editLabel = label;
		this.#editError = null;
		this.#emit();
	}

	setEditNote(note: string): void {
		if (!this.#editingId || this.#editSaving) return;
		this.#editNote = note;
		this.#emit();
	}

	cancelEdit(): void {
		if (this.#editSaving) return;
		this.#editingId = null;
		this.#editError = null;
		this.#emit();
	}

	async saveEdit(): Promise<void> {
		const id = this.#editingId;
		if (!id || this.#editSaving) return;
		const item = this.#find(id);
		if (!item || !annotationIsOwn(asLike(item), this.#meId)) return;
		const problem = labelProblem(this.#editLabel);
		if (problem) {
			this.#editError = problem;
			this.#emit();
			return;
		}
		const label = this.#editLabel.trim();
		const note = this.#editNote.trim();
		this.#editSaving = true;
		this.#editError = null;
		this.#emit();
		const result = await this.#client.update(id, { label, note: note.length > 0 ? note : null });
		if (this.#editingId !== id) return;
		this.#editSaving = false;
		if (!result.ok) {
			this.#editError = result.message;
			this.#emit();
			return;
		}
		this.#dropInflightList();
		this.#items = sortNewestFirst(this.#items.map((row) => (row.id === id ? result.item : row)));
		this.#editingId = null;
		this.#fetchKey = this.#key();
		this.#publishShapes();
		this.#emit();
	}

	requestDelete(id: string): void {
		const item = this.#find(id);
		if (!item || !annotationIsOwn(asLike(item), this.#meId) || this.#deleting) return;
		this.#confirmDeleteId = id;
		this.#deleteError = null;
		this.#editingId = null;
		this.#emit();
	}

	cancelDelete(): void {
		if (this.#deleting) return;
		this.#confirmDeleteId = null;
		this.#deleteError = null;
		this.#emit();
	}

	async confirmDelete(): Promise<void> {
		const id = this.#confirmDeleteId;
		if (!id || this.#deleting) return;
		const item = this.#find(id);
		if (!item || !annotationIsOwn(asLike(item), this.#meId)) return;
		this.#deleting = true;
		this.#deleteError = null;
		this.#emit();
		const result = await this.#client.remove(id);
		if (this.#confirmDeleteId !== id) return;
		this.#deleting = false;
		if (!result.ok) {
			this.#deleteError = result.message;
			this.#emit();
			return;
		}
		this.#dropInflightList();
		this.#items = this.#items.filter((row) => row.id !== id);
		if (this.#selectedId === id) this.#selectedId = null;
		this.#confirmDeleteId = null;
		this.#fetchKey = this.#key();
		this.#publishShapes();
		this.#emit();
	}

	#finishDraw(geom: DrawnGeometry): void {
		if (this.#draft?.phase !== 'drawing') return;
		const rounded = roundDrawn(geom, this.#host.getBounds());
		this.#draft = {
			phase: 'form',
			kind: geom.kind,
			geometry: rounded.ok ? rounded.geometry : null,
			label: '',
			note: '',
			error: rounded.ok ? null : rounded.message,
			source: 'tool'
		};
		this.#publishShapes();
		this.#emit();
	}

	#drawCancelled(): void {
		if (this.#draft?.phase !== 'drawing') return;
		this.#draft = null;
		this.#emit();
	}

	#fetch(slideId: string, key: string): Promise<void> {
		const token = ++this.#token;
		this.#inflightKey = key;
		if (this.#phase !== 'ready') {
			this.#phase = 'loading';
			this.#loadError = null;
			this.#publishShapes();
			this.#emit();
		}
		const pending = this.#client.list(slideId).then((result) => {
			if (token !== this.#token || this.#slideId !== slideId) return;
			this.#fetchKey = key;
			this.#inflightKey = '';
			if (!result.ok) {
				if (this.#phase === 'ready' && this.#items.length > 0) return;
				this.#phase = 'error';
				this.#loadError = result.message;
				this.#items = [];
				this.#publishShapes();
				this.#emit();
				return;
			}
			this.#phase = 'ready';
			this.#loadError = null;
			this.#items = sortNewestFirst(result.items);
			if (this.#selectedId && !this.#items.some((item) => item.id === this.#selectedId)) {
				this.#selectedId = null;
			}
			this.#publishShapes();
			this.#emit();
		});
		this.#inflight = pending;
		return pending;
	}

	#publishShapes(): void {
		const shapes =
			this.#phase === 'ready'
				? this.#items.map((item) => toViewerShape(asLike(item), this.#meId, this.#selectedId))
				: [];
		this.#host.setAnnotationShapes(shapes);
		if (this.#draft?.phase === 'drawing') return;
		const draft = this.#draft;
		this.#host.setDraft(
			draft?.geometry ? draftViewerShape(draft.kind, draft.geometry, draft.label) : null
		);
	}

	#row(item: AnnotationRecord, selectedId: string | null): AnnotationRow {
		const like = asLike(item);
		return {
			id: item.id,
			label: item.label,
			noteStart: notePreview(item.note),
			kind: item.kind,
			kindLabel: kindLabel(item.kind),
			authorName: item.author.name,
			synthetic: item.author.is_synthetic,
			createdAt: item.created_at,
			timeLabel: formatAnnotationTime(item.created_at),
			isOwn: annotationIsOwn(like, this.#meId),
			selected: item.id === selectedId,
			rect: regionHandoff(like) !== null
		};
	}

	#find(id: string): AnnotationRecord | undefined {
		return this.#items.find((item) => item.id === id);
	}

	#dropInflightList(): void {
		this.#token += 1;
		this.#inflightKey = '';
	}

	#key(): string {
		return `${this.#slideId ?? ''}|${this.#meId ?? ''}`;
	}

	#emit(): void {
		for (const listener of this.#listeners) listener();
	}
}

function labelProblem(label: string): string | null {
	const trimmed = label.trim();
	if (!trimmed) return 'A label is required.';
	if (trimmed.length > ANNOTATION_LABEL_MAX) {
		return `Use ${ANNOTATION_LABEL_MAX} characters or fewer for the label.`;
	}
	return null;
}

function createBody(
	kind: 'rect' | 'point',
	geometry: Level0Rect | Level0Point,
	label: string,
	note: string
): AnnotationCreateBody | null {
	const trimmed = label.trim();
	const noted = note.trim();
	const payloadNote = noted.length > 0 ? noted : null;
	if (kind === 'rect' && 'width' in geometry && 'height' in geometry) {
		return { kind: 'rect', geometry, label: trimmed, note: payloadNote };
	}
	if (kind === 'point' && !('width' in geometry)) {
		return {
			kind: 'point',
			geometry: { x: geometry.x, y: geometry.y },
			label: trimmed,
			note: payloadNote
		};
	}
	return null;
}

function asLike(item: AnnotationRecord): AnnotationLike {
	return item;
}
