<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { page } from '$app/state';
	import { Button, Typography } from '#lib';
	import { DEBUG_SAMPLE_WORD, installReportWordHook, readHeatmapDevHook } from './heatmap-dev.js';
	import { drawHeatmapPatches } from './heatmap-draw.js';
	import { loadSlideHeatmap } from './heatmap-load.js';
	import { SIMILARITY_LABEL, type HeatmapPatchScore } from './heatmap-ramp.js';
	import {
		EMPTY_HEATMAP_VIEW,
		reduceHeatmap,
		syncHeatmapTarget,
		type HeatmapView
	} from './heatmap-session.js';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret

	let view = $state<HeatmapView>(EMPTY_HEATMAP_VIEW);
	const painted: { patches: readonly HeatmapPatchScore[] } = { patches: [] };
	let appliedUrlWord = false;

	const devHook = $derived(readHeatmapDevHook(page.url.search));
	const showDebug = $derived(devHook.debugOverlay && view.phrase == null);

	function publish(next: HeatmapView) {
		view = next;
		painted.patches = next.overlay?.patches ?? [];
		caseState.invalidateLayer('heatmap');
	}

	$effect(() => {
		const word = readHeatmapDevHook(page.url.search).word;
		const slideId = caseState.activeSlideId;
		if (appliedUrlWord || !word || !slideId) return;
		appliedUrlWord = true;
		if (untrack(() => caseState.heatmapPhraseRequest)) return;
		caseState.requestHeatmapPhrase(word);
	});

	$effect(() => {
		const request = caseState.heatmapPhraseRequest;
		const slideId = caseState.activeSlideId;
		const phrase = request?.phrase?.trim() ?? '';
		const seq = request && phrase && slideId ? request.seq : null;
		const next = syncHeatmapTarget(
			untrack(() => view),
			{
				slideId,
				phrase: seq == null ? null : phrase,
				seq
			}
		);
		if (next !== untrack(() => view)) publish(next);
		if (!next.loading || next.seq == null || !next.slideId || !next.phrase) return;

		const controller = new AbortController();
		const requestedSlide = next.slideId;
		const requestedSeq = next.seq;
		const requestedPhrase = next.phrase;
		let dropped = false;

		void loadSlideHeatmap(requestedSlide, requestedPhrase, controller.signal).then((result) => {
			if (dropped || result.kind === 'aborted') return;
			const current = untrack(() => view);
			const reduced =
				result.kind === 'ok'
					? reduceHeatmap(current, {
							type: 'success',
							slideId: requestedSlide,
							seq: requestedSeq,
							phrase: result.text,
							patches: result.patches
						})
					: reduceHeatmap(current, {
							type: 'failure',
							slideId: requestedSlide,
							seq: requestedSeq,
							message: result.message
						});
			if (reduced === current) return;
			publish(reduced);
		});

		return () => {
			dropped = true;
			controller.abort();
		};
	});

	onMount(() => {
		const unregister = caseState.registerLayerDrawer('heatmap', (ctx, proj) => {
			drawHeatmapPatches(ctx, proj, painted.patches);
		});
		const removeHook = installReportWordHook((phrase) => {
			caseState.requestHeatmapPhrase(phrase);
		});
		return () => {
			unregister();
			removeHook();
		};
	});
</script>

<div class="heatmap-controls">
	{#if view.phrase}
		<div
			class="pill"
			role="status"
			aria-live="polite"
			aria-busy={view.loading}
			data-heatmap-word={view.phrase}
			data-heatmap-label={SIMILARITY_LABEL}
			data-heatmap-loading={view.loading ? 'true' : 'false'}
			data-heatmap-error={view.error ?? ''}
		>
			<div class="copy">
				<div class="line">
					<Typography as="span" style="label" tone="inverse">{view.phrase}</Typography>
					{#if view.loading}
						<span class="spinner" aria-hidden="true"></span>
						<Typography as="span" style="small" tone="inverse">Computing similarity</Typography>
					{/if}
				</div>
				<p class="notice">{SIMILARITY_LABEL}</p>
				{#if view.error}
					<p class="error" role="alert">{view.error}</p>
				{/if}
			</div>
			<Button variant="secondary" size="sm" onclick={() => caseState.requestHeatmapPhrase(null)}>
				Clear
			</Button>
		</div>
	{/if}
	{#if showDebug}
		<button
			type="button"
			class="debug"
			data-heatmap-debug
			onclick={() => caseState.requestHeatmapPhrase(DEBUG_SAMPLE_WORD)}
		>
			Dev hook: shade {DEBUG_SAMPLE_WORD}
		</button>
	{/if}
</div>

<style>
	.heatmap-controls {
		position: absolute;
		z-index: 8;
		top: 0;
		right: 0;
		left: 0;
		display: flex;
		justify-content: center;
		padding: var(--space-4) 6rem 0;
		pointer-events: none;
	}
	.heatmap-controls:empty {
		display: none;
	}
	.pill,
	.debug {
		pointer-events: auto;
	}
	.pill {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		max-width: min(40rem, 100%);
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-pill);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
	}
	.copy {
		display: grid;
		gap: 0.125rem;
		min-width: 0;
	}
	.line {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}
	.notice,
	.error {
		margin: 0;
		font: var(--font-small);
	}
	.notice {
		color: var(--color-viewer-text);
	}
	.error {
		color: #ffc7c7;
	}
	.spinner {
		width: 0.8rem;
		height: 0.8rem;
		flex: none;
		border: 2px solid rgba(255, 255, 255, 0.35);
		border-top-color: #ffbc30;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}
	.debug {
		padding: var(--space-2) var(--space-3);
		border: var(--border-width) dashed var(--color-viewer-border);
		border-radius: var(--radius-pill);
		background: var(--color-viewer-panel);
		color: var(--color-viewer-text);
		font: var(--font-label-sm);
		cursor: pointer;
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
