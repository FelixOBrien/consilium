<script lang="ts" module>
	/** One watcher per case view, so the overlay keeps up after this panel unmounts. */
	const watchedViews = new WeakSet<object>();
</script>

<script lang="ts">
	import {
		Badge,
		Button,
		EmptyState,
		Skeleton,
		StateMessage,
		TextArea,
		TextField,
		Typography
	} from '#lib';
	import { identity } from '#lib/identity/identity.svelte.js';
	import { geometrySummary } from './annotations-geometry.js';
	import {
		AnnotationsSession,
		sharedAnnotationsSession,
		type AnnotationHost
	} from './annotations-session.js';
	import type { ViewerAnnotationShape } from './overlay-layers.js';
	// prettier-ignore
	import { getWorkspaceContext as getViewContext, type WorkspaceState as ViewState } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const view = getViewContext();
	const session = sharedAnnotationsSession(view, () => new AnnotationsSession(hostPort(view)));

	let snapshot = $state(session.snapshot());
	let seenFocus = 0;

	if (!watchedViews.has(view)) {
		watchedViews.add(view);
		$effect.root(() => {
			$effect(() => {
				const slideId = view.activeSlideId;
				const meId = identity.me?.id ?? null;
				void identity.revision;
				void session.sync(slideId, meId);
			});

			$effect(() => {
				const pending = view.pendingAnnotationRegion;
				const slideId = view.activeSlideId;
				if (pending) session.offerSelection(pending, slideId);
			});

			view.onSelectAnnotation = (id) => {
				session.highlight(id, true);
			};
		});
	}

	$effect(() => {
		snapshot = session.snapshot();
		return session.subscribe(() => {
			snapshot = session.snapshot();
		});
	});

	$effect(() => {
		const request = snapshot.focusRequest;
		if (!request || request.nonce === seenFocus) return;
		seenFocus = request.nonce;
		const node = document.getElementById(`annotation-${request.id}`);
		node?.focus();
		node?.scrollIntoView({ block: 'nearest' });
	});

	const drawingRect = $derived(
		snapshot.draft?.phase === 'drawing' && snapshot.draft.kind === 'rect'
	);
	const drawingPoint = $derived(
		snapshot.draft?.phase === 'drawing' && snapshot.draft.kind === 'point'
	);
	const formOpen = $derived(snapshot.draft?.phase === 'form' || snapshot.draft?.phase === 'saving');
	const saving = $derived(snapshot.draft?.phase === 'saving');
	const geometryLine = $derived(
		snapshot.draft ? geometrySummary(snapshot.draft.kind, snapshot.draft.geometry) : null
	);

	function onWindowKeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape') return;
		if (snapshot.confirmDeleteId) {
			session.cancelDelete();
			return;
		}
		if (snapshot.editingId && !snapshot.draft) {
			session.cancelEdit();
			return;
		}
		if (!snapshot.draft || snapshot.draft.phase === 'saving') return;
		event.preventDefault();
		session.cancel();
	}

	function hostPort(state: ViewState): AnnotationHost {
		return {
			setAnnotationShapes: (shapes) => state.setAnnotationShapes(shapes),
			setDraft: (shape: ViewerAnnotationShape | null) => {
				state.draftAnnotationShape = shape;
			},
			startAnnotationDraw: (kind, onComplete, onCancel) =>
				state.startAnnotationDraw(kind, onComplete, onCancel),
			cancelInteractionMode: () => state.cancelInteractionMode(),
			flyToLevel0: (target) => state.flyToLevel0(target),
			triggerEvidenceSearch: (region) =>
				state.triggerEvidenceSearch({
					kind: 'region',
					slideId: region.slideId,
					x: region.x,
					y: region.y,
					width: region.width,
					height: region.height
				}),
			attachToConsult: (region) =>
				state.attachToConsult({
					kind: 'region',
					slideId: region.slideId,
					x: region.x,
					y: region.y,
					width: region.width,
					height: region.height,
					label: region.label
				}),
			getBounds: () => {
				const slide = state.activeSlide;
				if (!slide || slide.width < 1 || slide.height < 1) return null;
				return { width: slide.width, height: slide.height };
			}
		};
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<section
	class="annotations"
	data-testid="annotations-panel"
	data-phase={snapshot.phase}
	data-draft={snapshot.draft?.phase ?? 'none'}
	aria-labelledby="annotations-heading"
	aria-busy={snapshot.phase === 'loading'}
>
	<header class="intro">
		<Typography style="eyebrow" tone="muted">Annotations</Typography>
		<h2 id="annotations-heading">
			<Typography as="span" style="section">Marks on this slide</Typography>
		</h2>
		<Typography tone="secondary">
			Draw a rectangle or place a point, then label it. Marks are shared notes on the tissue, not a
			diagnosis.
		</Typography>
	</header>

	<div class="tools" role="group" aria-label="Drawing tools">
		<Button
			variant={drawingRect ? 'primary' : 'secondary'}
			disabled={saving || snapshot.editSaving}
			onclick={() => session.startDraw('rect')}
		>
			Rectangle
		</Button>
		<Button
			variant={drawingPoint ? 'primary' : 'secondary'}
			disabled={saving || snapshot.editSaving}
			onclick={() => session.startDraw('point')}
		>
			Point
		</Button>
		{#if snapshot.draft && !saving}
			<Button variant="ghost" onclick={() => session.cancel()}>Cancel</Button>
		{/if}
	</div>

	<button
		type="button"
		class="layer-toggle"
		data-testid="layer-toggle"
		aria-pressed={view.layers.annotations}
		onclick={() => view.toggleLayer('annotations')}
	>
		<span class="tick" class:on={view.layers.annotations} aria-hidden="true"></span>
		{view.layers.annotations ? 'Annotations visible' : 'Annotations hidden'}
	</button>
	{#if !view.layers.annotations}
		<Typography style="small" tone="muted">Hidden on the viewer. The list is unchanged.</Typography>
	{/if}

	{#if drawingRect}
		<div class="status" role="status">
			<StateMessage
				tone="info"
				title="Drawing a rectangle"
				description="Drag on the tissue. Patch selection and drag-to-pan are paused until you finish or cancel."
				action="Cancel"
				onaction={() => session.cancel()}
			/>
		</div>
	{:else if drawingPoint}
		<div class="status" role="status">
			<StateMessage
				tone="info"
				title="Placing a point"
				description="Click the tissue. Patch selection and drag-to-pan are paused until you place the point or cancel."
				action="Cancel"
				onaction={() => session.cancel()}
			/>
		</div>
	{/if}

	{#if formOpen && snapshot.draft}
		<form
			class="mark-form"
			data-testid="annotation-form"
			onsubmit={(event) => {
				event.preventDefault();
				void session.save();
			}}
		>
			<Typography style="label">
				{snapshot.draft.source === 'selection' ? 'Label the selected region' : 'Label this mark'}
			</Typography>
			{#if geometryLine}
				<Typography style="small" tone="secondary">{geometryLine}</Typography>
			{/if}
			<TextField
				label="Label"
				icon="annotation"
				placeholder="Short label"
				disabled={saving}
				bind:value={() => snapshot.draft?.label ?? '', (label) => session.setDraftLabel(label)}
			/>
			<TextArea
				label="Note, optional"
				rows={3}
				bind:value={() => snapshot.draft?.note ?? '', (note) => session.setDraftNote(note)}
			/>
			{#if snapshot.draft.error}
				<div role="alert">
					<StateMessage tone="danger" title="Could not save" description={snapshot.draft.error} />
				</div>
			{/if}
			<div class="actions">
				<Button type="submit" variant="primary" disabled={saving || !snapshot.draft.geometry}>
					{saving ? 'Saving…' : 'Save annotation'}
				</Button>
				<Button variant="secondary" disabled={saving} onclick={() => session.cancel()}
					>Cancel</Button
				>
			</div>
		</form>
	{/if}

	{#if snapshot.phase === 'loading'}
		<div class="loading" aria-hidden="true">
			<Skeleton height="lg" />
			<Skeleton height="lg" />
			<Skeleton height="md" width="medium" />
		</div>
	{:else if snapshot.phase === 'error'}
		<StateMessage
			tone="danger"
			title="Annotations could not be loaded"
			description={snapshot.loadError ?? 'The list could not be loaded.'}
			action="Retry"
			onaction={() => void session.reload()}
		/>
	{:else if snapshot.items.length === 0 && !formOpen && !drawingRect && !drawingPoint}
		<EmptyState
			icon="annotation"
			title="No annotations on this slide"
			description="Choose Rectangle and drag on the tissue, or choose Point and click. Add a label and the mark stays on that tissue when you zoom."
			action="Draw a rectangle"
			onaction={() => session.startDraw('rect')}
		/>
	{:else if snapshot.items.length > 0}
		<ul class="marks" data-testid="annotation-list" aria-label="Annotations on this slide">
			{#each snapshot.items as item (item.id)}
				<li
					id="annotation-{item.id}"
					class:own={item.isOwn}
					class:selected={item.selected}
					data-own={item.isOwn}
					data-kind={item.kind}
					tabindex="-1"
				>
					{#if snapshot.editingId === item.id}
						<form
							class="edit-form"
							data-testid="edit-form"
							onsubmit={(event) => {
								event.preventDefault();
								void session.saveEdit();
							}}
						>
							<TextField
								label="Label"
								icon="annotation"
								disabled={snapshot.editSaving}
								bind:value={() => snapshot.editLabel, (label) => session.setEditLabel(label)}
							/>
							<TextArea
								label="Note, optional"
								rows={3}
								bind:value={() => snapshot.editNote, (note) => session.setEditNote(note)}
							/>
							{#if snapshot.editError}
								<div role="alert">
									<StateMessage
										tone="danger"
										title="Could not update"
										description={snapshot.editError}
									/>
								</div>
							{/if}
							<div class="actions">
								<Button type="submit" variant="primary" disabled={snapshot.editSaving}>
									{snapshot.editSaving ? 'Saving…' : 'Save changes'}
								</Button>
								<Button
									variant="secondary"
									disabled={snapshot.editSaving}
									onclick={() => session.cancelEdit()}
								>
									Cancel
								</Button>
							</div>
						</form>
					{:else}
						<div class="mark-top">
							<button type="button" class="mark-label" onclick={() => session.goTo(item.id)}>
								{item.label}
							</button>
							<Badge tone={item.isOwn ? 'info' : 'neutral'}>
								{item.isOwn ? 'Yours' : item.kindLabel}
							</Badge>
							{#if item.isOwn}
								<Badge tone="neutral">{item.kindLabel}</Badge>
							{/if}
						</div>
						<Typography style="small" tone="secondary">
							{item.authorName}
							{#if item.synthetic}
								<Badge tone="synthetic">Synthetic</Badge>
							{/if}
							<span class="dot">·</span>
							<time datetime={item.createdAt}>{item.timeLabel}</time>
						</Typography>
						{#if item.noteStart}
							<Typography style="small">{item.noteStart}</Typography>
						{/if}
						{#if snapshot.confirmDeleteId === item.id}
							<div class="confirm" role="group" aria-label={`Delete ${item.label}`}>
								<Typography style="small">
									Delete “{item.label}”? This removes it for everyone who opens the slide.
								</Typography>
								{#if snapshot.deleteError}
									<div role="alert">
										<StateMessage
											tone="danger"
											title="Could not delete"
											description={snapshot.deleteError}
										/>
									</div>
								{/if}
								<div class="actions">
									<Button
										variant="danger"
										disabled={snapshot.deleting}
										onclick={() => void session.confirmDelete()}
									>
										{snapshot.deleting ? 'Deleting…' : 'Delete annotation'}
									</Button>
									<Button
										variant="secondary"
										disabled={snapshot.deleting}
										onclick={() => session.cancelDelete()}
									>
										Keep
									</Button>
								</div>
							</div>
						{:else}
							<div class="actions">
								<Button size="sm" variant="secondary" onclick={() => session.goTo(item.id)}
									>Go to</Button
								>
								{#if item.rect}
									<Button
										size="sm"
										variant="secondary"
										onclick={() => session.findSimilar(item.id)}
									>
										Find similar tissue
									</Button>
									<Button size="sm" variant="secondary" onclick={() => session.ask(item.id)}>
										Ask about this region
									</Button>
								{/if}
								{#if item.isOwn && !snapshot.draft}
									<Button size="sm" variant="ghost" onclick={() => session.beginEdit(item.id)}
										>Edit</Button
									>
									<Button size="sm" variant="danger" onclick={() => session.requestDelete(item.id)}>
										Delete
									</Button>
								{/if}
							</div>
						{/if}
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.annotations {
		display: grid;
		align-content: start;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.intro {
		display: grid;
		gap: var(--space-2);
	}
	h2 {
		margin: 0;
	}
	.tools,
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.layer-toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		justify-self: start;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
		cursor: pointer;
	}
	.tick {
		width: 1rem;
		height: 1rem;
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-xs);
		background: var(--color-surface);
		box-shadow: var(--shadow-inset);
	}
	.tick.on {
		border-color: var(--color-action);
		background: var(--color-action);
		box-shadow: inset 0 0 0 0.2rem var(--color-surface);
	}
	.layer-toggle:focus-visible {
		outline: var(--focus-ring);
		outline-offset: var(--focus-offset);
		border-radius: var(--radius-sm);
	}
	.mark-form,
	.edit-form,
	.confirm {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.loading {
		display: grid;
		gap: var(--space-3);
	}
	.marks {
		display: grid;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.marks > li {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.marks > li.own {
		border-color: var(--color-info-border);
	}
	.marks > li.selected {
		border-color: var(--color-action);
		background: var(--color-action-soft);
		box-shadow: var(--shadow-focus);
	}
	.marks > li:focus {
		outline: var(--focus-ring);
		outline-offset: var(--focus-offset);
	}
	.mark-top {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.mark-label {
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--color-text);
		font: var(--font-label);
		text-align: left;
		cursor: pointer;
	}
	.mark-label:hover {
		color: var(--color-action);
	}
	.dot {
		margin: 0 var(--space-1);
	}
	.status :global(.state-message) {
		width: 100%;
	}
</style>
