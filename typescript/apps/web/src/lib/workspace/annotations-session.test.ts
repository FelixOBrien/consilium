import { describe, expect, test } from 'bun:test';
import { messageFromApiError, type AnnotationApi, type AnnotationRecord } from './annotations-api';
import {
	AnnotationsSession,
	type AnnotationHost,
	type SelectionRegion
} from './annotations-session';
import type { ViewerAnnotationShape } from './overlay-layers';
import type { DrawnGeometry } from './annotations-geometry';

function mark(overrides: Partial<AnnotationRecord> = {}): AnnotationRecord {
	return {
		id: overrides.id ?? 'ann-1',
		slide_id: overrides.slide_id ?? 'slide-a',
		case_id: 'case-a',
		author: overrides.author ?? {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		can_edit: overrides.can_edit ?? true,
		kind: overrides.kind ?? 'rect',
		geometry: overrides.geometry ?? { x: 128, y: 64, width: 512, height: 256 },
		label: overrides.label ?? 'Fixture region',
		note: overrides.note === undefined ? 'Synthetic mark' : overrides.note,
		created_at: overrides.created_at ?? '2026-11-03T11:00:00.000Z',
		updated_at: overrides.updated_at ?? '2026-11-03T11:00:00.000Z'
	};
}

function deferred<T>() {
	let resolve: (value: T) => void = () => {};
	const promise = new Promise<T>((done) => {
		resolve = done;
	});
	return { promise, resolve };
}

function harness(bounds: { width: number; height: number } | null = { width: 2048, height: 1536 }) {
	const shapes: ViewerAnnotationShape[][] = [];
	const drafts: (ViewerAnnotationShape | null)[] = [];
	const draws: Array<'rect' | 'point'> = [];
	const flies: unknown[] = [];
	const evidence: unknown[] = [];
	const consult: unknown[] = [];
	let cancels = 0;
	let onComplete: ((geom: DrawnGeometry) => void) | null = null;
	let onCancel: (() => void) | null = null;
	const created: unknown[] = [];
	const updated: unknown[] = [];
	const removed: string[] = [];
	const lists: string[] = [];
	let listResult: (
		slideId: string
	) => Promise<Awaited<ReturnType<AnnotationApi['list']>>> = async () => ({
		ok: true,
		items: []
	});

	const host: AnnotationHost = {
		setAnnotationShapes(next) {
			shapes.push(next);
		},
		setDraft(shape) {
			drafts.push(shape);
		},
		startAnnotationDraw(kind, complete, cancel) {
			const previous = onCancel;
			onComplete = null;
			onCancel = null;
			previous?.();
			draws.push(kind);
			onComplete = complete;
			onCancel = cancel ?? null;
		},
		cancelInteractionMode() {
			cancels += 1;
			const cancel = onCancel;
			onComplete = null;
			onCancel = null;
			cancel?.();
		},
		flyToLevel0(target) {
			flies.push(target);
		},
		triggerEvidenceSearch(region) {
			evidence.push(region);
		},
		attachToConsult(region) {
			consult.push(region);
		},
		getBounds: () => bounds
	};

	const client: AnnotationApi = {
		list(slideId) {
			lists.push(slideId);
			return listResult(slideId);
		},
		async create(_slideId, body) {
			created.push(body);
			return {
				ok: true,
				item: mark({
					id: 'created',
					kind: body.kind,
					geometry: body.geometry,
					label: body.label,
					note: body.note ?? null,
					created_at: '2026-11-14T12:00:00.000Z'
				})
			};
		},
		async update(id, body) {
			updated.push({ id, body });
			return {
				ok: true,
				item: mark({ id, label: body.label ?? 'Updated', note: body.note ?? null })
			};
		},
		async remove(id) {
			removed.push(id);
			return { ok: true };
		}
	};

	const session = new AnnotationsSession(host, client);
	return {
		session,
		host,
		shapes,
		drafts,
		draws,
		flies,
		evidence,
		consult,
		created,
		updated,
		removed,
		lists,
		get cancels() {
			return cancels;
		},
		complete(geom: DrawnGeometry) {
			const done = onComplete;
			onComplete = null;
			onCancel = null;
			done?.(geom);
		},
		setList(next: (slideId: string) => Promise<Awaited<ReturnType<AnnotationApi['list']>>>) {
			listResult = next;
		},
		failCreate(message: string) {
			client.create = async (_slideId, body) => {
				created.push(body);
				return { ok: false, message };
			};
		}
	};
}

const region: SelectionRegion = {
	slideId: 'slide-a',
	x: 10.4,
	y: 20.6,
	width: 30.2,
	height: 40.8,
	seq: 1
};

describe('annotation session', () => {
	test('loads a slide into the viewer and swaps the layer when the slide changes', async () => {
		const box = harness();
		const first = mark();
		const second = mark({
			id: 'point-b',
			slide_id: 'slide-b',
			kind: 'point',
			geometry: { x: 4, y: 9 },
			label: 'Point'
		});
		box.setList(async (slideId) => ({
			ok: true,
			items: slideId === 'slide-a' ? [first] : [second]
		}));

		await box.session.sync('slide-a', 'path-okafor');
		expect(box.cancels).toBe(0);
		expect(box.session.snapshot().items.map((item) => item.label)).toEqual(['Fixture region']);
		expect(box.shapes.at(-1)).toEqual([
			{
				id: 'ann-1',
				kind: 'rect',
				x: 128,
				y: 64,
				w: 512,
				h: 256,
				label: 'Fixture region',
				isOwn: true,
				selected: false
			}
		]);

		const pending = deferred<Awaited<ReturnType<AnnotationApi['list']>>>();
		box.setList(() => pending.promise);
		const loading = box.session.sync('slide-b', 'path-okafor');
		expect(box.session.snapshot().phase).toBe('loading');
		expect(box.session.snapshot().items).toEqual([]);
		expect(box.shapes.at(-1)).toEqual([]);
		pending.resolve({ ok: true, items: [second] });
		await loading;
		expect(box.session.snapshot().items.map((item) => item.id)).toEqual(['point-b']);
		expect(box.shapes.at(-1)?.[0]).toEqual({
			id: 'point-b',
			kind: 'point',
			x: 4,
			y: 9,
			label: 'Point',
			isOwn: true,
			selected: false
		});
	});

	test('flips isOwn when the acting pathologist changes before the list returns', async () => {
		const box = harness();
		box.setList(async () => ({ ok: true, items: [mark({ can_edit: true })] }));
		await box.session.sync('slide-a', 'path-okafor');
		expect(box.session.snapshot().items[0]?.isOwn).toBe(true);

		const pending = deferred<Awaited<ReturnType<AnnotationApi['list']>>>();
		box.setList(() => pending.promise);
		const refresh = box.session.sync('slide-a', 'path-mensah');
		expect(box.session.snapshot().items[0]?.isOwn).toBe(false);
		expect(box.shapes.at(-1)?.[0]?.isOwn).toBe(false);
		expect(box.session.snapshot().items[0]?.authorName).toBe('Dr A. Okafor');
		pending.resolve({
			ok: true,
			items: [mark({ can_edit: false })]
		});
		await refresh;
		expect(box.session.snapshot().items[0]?.isOwn).toBe(false);
	});

	test('rounds a drawn rectangle, keeps it when save fails, and posts integer level-0 pixels', async () => {
		const box = harness();
		await box.session.sync('slide-a', 'path-okafor');
		box.session.startDraw('rect');
		expect(box.draws).toEqual(['rect']);
		expect(box.session.snapshot().draft?.phase).toBe('drawing');
		box.complete({ kind: 'rect', x: 10.4, y: 20.6, w: 30.5, h: 40.2 });
		expect(box.session.snapshot().draft?.phase).toBe('form');
		expect(box.session.snapshot().draft?.geometry).toEqual({ x: 10, y: 21, width: 31, height: 40 });
		expect(box.drafts.at(-1)).toEqual({
			id: 'draft',
			kind: 'rect',
			x: 10,
			y: 21,
			w: 31,
			h: 40,
			label: '',
			isOwn: true,
			selected: true
		});

		box.session.setDraftLabel('  Inked margin  ');
		box.session.setDraftNote('  optional note  ');
		box.failCreate('Geometry is outside the slide.');
		await box.session.save();
		expect(box.session.snapshot().draft?.phase).toBe('form');
		expect(box.session.snapshot().draft?.error).toBe('Geometry is outside the slide.');
		expect(box.drafts.at(-1)?.id).toBe('draft');
		expect(box.created[0]).toEqual({
			kind: 'rect',
			geometry: { x: 10, y: 21, width: 31, height: 40 },
			label: 'Inked margin',
			note: 'optional note'
		});

		box.session.cancel();
		expect(box.cancels).toBeGreaterThan(0);
		expect(box.session.snapshot().draft).toBeNull();
		expect(box.drafts.at(-1)).toBeNull();
	});

	test('opens a viewer selection once, ready to save as a rectangle', async () => {
		const box = harness();
		await box.session.sync('slide-a', 'path-okafor');
		box.session.offerSelection(region, 'slide-a');
		box.session.setDraftLabel('Kept');
		box.session.offerSelection(region, 'slide-a');
		expect(box.session.snapshot().draft?.label).toBe('Kept');
		expect(box.session.snapshot().draft?.source).toBe('selection');
		expect(box.session.snapshot().draft?.geometry).toEqual({
			x: Math.round(region.x),
			y: Math.round(region.y),
			width: Math.round(region.width),
			height: Math.round(region.height)
		});

		box.session.offerSelection({ ...region, seq: 2, x: 4 }, 'slide-b');
		expect(box.session.snapshot().draft?.label).toBe('Kept');
		box.session.offerSelection({ ...region, seq: 3, x: 8.2 }, 'slide-a');
		expect(box.session.snapshot().draft?.geometry).toEqual({
			x: Math.round(8.2),
			y: Math.round(region.y),
			width: Math.round(region.width),
			height: Math.round(region.height)
		});
		expect(box.session.snapshot().draft?.label).toBe('');
	});

	test('edits and deletes only for the author, and delete waits for confirmation', async () => {
		const box = harness();
		const mine = mark({ id: 'mine' });
		const theirs = mark({
			id: 'theirs',
			label: 'Colleague',
			can_edit: true,
			author: {
				id: 'path-mensah',
				name: 'Dr E. Mensah',
				primary_specialty: 'breast',
				is_synthetic: true
			},
			created_at: '2026-11-02T11:00:00.000Z'
		});
		box.setList(async () => ({ ok: true, items: [mine, theirs] }));
		await box.session.sync('slide-a', 'path-okafor');
		const rows = box.session.snapshot().items;
		expect(rows.map((item) => item.id)).toEqual(['mine', 'theirs']);
		expect(rows.find((item) => item.id === 'theirs')?.isOwn).toBe(false);

		box.session.beginEdit('theirs');
		expect(box.session.snapshot().editingId).toBeNull();
		box.session.requestDelete('theirs');
		expect(box.removed).toEqual([]);
		expect(box.session.snapshot().confirmDeleteId).toBeNull();

		box.session.beginEdit('mine');
		box.session.setEditLabel('Renamed');
		box.session.setEditNote('');
		await box.session.saveEdit();
		expect(box.updated[0]).toEqual({ id: 'mine', body: { label: 'Renamed', note: null } });
		expect(box.session.snapshot().editingId).toBeNull();

		box.session.requestDelete('mine');
		expect(box.removed).toEqual([]);
		expect(box.session.snapshot().confirmDeleteId).toBe('mine');
		box.session.cancelDelete();
		expect(box.session.snapshot().confirmDeleteId).toBeNull();
		box.session.requestDelete('mine');
		await box.session.confirmDelete();
		expect(box.removed).toEqual(['mine']);
		expect(box.session.snapshot().items.map((item) => item.id)).toEqual(['theirs']);
	});

	test('go to, find similar tissue, and ask about a rectangle use the shared handoffs', async () => {
		const box = harness();
		const point = mark({
			id: 'point',
			kind: 'point',
			geometry: { x: 12, y: 14 },
			label: 'Spot',
			created_at: '2026-11-01T00:00:00.000Z'
		});
		box.setList(async () => ({ ok: true, items: [mark(), point] }));
		await box.session.sync('slide-a', 'path-okafor');

		box.session.goTo('ann-1');
		expect(box.flies[0]).toEqual({ slideId: 'slide-a', x: 128, y: 64, width: 512, height: 256 });
		expect(box.shapes.at(-1)?.find((shape) => shape.id === 'ann-1')?.selected).toBe(true);

		box.session.findSimilar('ann-1');
		expect(box.evidence[0]).toEqual({ slideId: 'slide-a', x: 128, y: 64, width: 512, height: 256 });
		box.session.ask('ann-1');
		expect(box.consult[0]).toEqual({
			slideId: 'slide-a',
			x: 128,
			y: 64,
			width: 512,
			height: 256,
			label: 'Fixture region'
		});
		box.session.findSimilar('point');
		box.session.ask('point');
		expect(box.evidence).toHaveLength(1);
		expect(box.consult).toHaveLength(1);

		box.session.highlight('point', true);
		expect(box.session.snapshot().focusRequest).toEqual({ id: 'point', nonce: 1 });
		expect(box.session.snapshot().selectedId).toBe('point');
	});

	test('requires a label and leaves the shape in place', async () => {
		const box = harness();
		await box.session.sync('slide-a', 'path-okafor');
		box.session.startDraw('point');
		box.complete({ kind: 'point', x: 3.6, y: 4.2 });
		await box.session.save();
		expect(box.created).toEqual([]);
		expect(box.session.snapshot().draft?.error).toBe('A label is required.');
		expect(box.session.snapshot().draft?.geometry).toEqual({ x: 4, y: 4 });
	});

	test('reads an API error message', () => {
		expect(
			messageFromApiError(
				{ error: { code: 'forbidden', message: 'Only the author can change this annotation.' } },
				'fallback'
			)
		).toBe('Only the author can change this annotation.');
		expect(messageFromApiError(null, 'fallback')).toBe('fallback');
	});
});
