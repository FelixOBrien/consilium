<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Button, EmptyState, Typography } from '#lib';
	import ComparePane from '#lib/compare/ComparePane.svelte';
	import {
		COMPARE_FRAMING,
		MISSING_COMPARE_BODY,
		MISSING_COMPARE_TITLE
	} from '#lib/compare/copy.js';
	import { LinkSession, type PaneController, type Side } from '#lib/compare/link.js';
	import { physicalScaleAvailable } from '#lib/compare/scale.js';
	import {
		hasSlidePair,
		locus,
		missingCompareHint,
		parseCompareQuery,
		queryFromViews,
		writeCompareQuery
	} from '#lib/compare/url.js';

	const pageTitle = 'Compare slides · Consilium'; // pragma: allowlist secret

	const initial = parseCompareQuery(page.url.searchParams);
	const paired = hasSlidePair(initial);
	const slides = paired ? { left: initial.left, right: initial.right } : null;
	const leftRestore = { x: initial.lx, y: initial.ly, zoom: initial.lzoom };
	const rightRestore = { x: initial.rx, y: initial.ry, zoom: initial.rzoom };
	const leftMark = locus(initial.lx, initial.ly);
	const rightMark = locus(initial.rx, initial.ry);

	let syncOn = $state(initial.sync);
	let relativeScale = $state(false);
	const session = new LinkSession(initial.sync);
	const panes: Record<Side, PaneController | null> = { left: null, right: null };
	const mpps: Record<Side, number | null> = { left: null, right: null };
	let urlTimer: ReturnType<typeof setTimeout> | null = null;

	function register(side: Side, controller: PaneController, mpp: number | null) {
		panes[side] = controller;
		mpps[side] = mpp;
		if (panes.left && panes.right) {
			relativeScale = !physicalScaleAvailable(mpps.left, mpps.right);
		}
		const left = panes.left?.read() ?? null;
		const right = panes.right?.read() ?? null;
		if (left && right && syncOn) {
			const aligned = session.relink(left, right, mpps.left, mpps.right);
			if (Math.abs(aligned.zoom - right.zoom) > 1e-6) {
				panes.right?.apply(aligned);
				const actual = panes.right?.read();
				if (actual) session.note('right', actual);
			}
		}
	}

	function gesture(side: Side) {
		if (!syncOn) return;
		const left = panes.left?.read() ?? null;
		const right = panes.right?.read() ?? null;
		if (left && right && session.leading === null) session.setBaseline(left, right);
		session.claim(side);
	}

	function move(side: Side) {
		const view = panes[side]?.read();
		if (!view) return;
		if (session.leading === side) {
			const linked = session.observe(side, view, mpps);
			if (!linked) return;
			panes[linked.side]?.apply(linked.view);
			const actual = panes[linked.side]?.read();
			if (actual) session.note(linked.side, actual);
			return;
		}
		if (session.leading === null) session.note(side, view);
	}

	function settle(side: Side) {
		if (session.leading === side) session.release();
		const view = panes[side]?.read();
		if (view && session.leading === null) session.note(side, view);
		scheduleUrl();
	}

	function toggleSync() {
		if (syncOn) {
			session.unlink();
			syncOn = false;
			scheduleUrl(0);
			return;
		}
		const left = panes.left?.read() ?? null;
		const right = panes.right?.read() ?? null;
		if (left && right) {
			const aligned = session.relink(left, right, mpps.left, mpps.right);
			panes.right?.apply(aligned);
		} else {
			session.sync = true;
		}
		syncOn = true;
		scheduleUrl(0);
	}

	function scheduleUrl(delay = 80) {
		if (!slides) return;
		if (urlTimer) clearTimeout(urlTimer);
		urlTimer = setTimeout(writeUrl, delay);
	}

	function writeUrl() {
		if (!slides) return;
		const next = queryFromViews(
			slides,
			panes.left?.read() ?? null,
			panes.right?.read() ?? null,
			syncOn,
			initial
		);
		const url = writeCompareQuery(page.url, next);
		// Viewport numbers are query state. resolve() only accepts the route id.
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		void replaceState(`${resolve('/compare')}?${url.searchParams.toString()}`, page.state);
	}
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

<div class="compare-page" data-screen="compare">
	<header class="compare-bar">
		<div class="bar-copy">
			<Typography as="span" style="eyebrow" tone="accent">Compare</Typography>
			<Typography as="h1" style="subsection">Side by side</Typography>
			<Typography as="p" style="small" tone="secondary">{COMPARE_FRAMING}</Typography>
		</div>
		{#if slides}
			<div class="sync">
				<Typography as="span" style="label">{syncOn ? 'Linked' : 'Unlinked'}</Typography>
				<Button
					variant={syncOn ? 'primary' : 'secondary'}
					size="sm"
					ariaLabel={syncOn ? 'Unlink pan and zoom' : 'Link pan and zoom'}
					onclick={toggleSync}
				>
					{syncOn ? 'Unlink' : 'Link'}
				</Button>
			</div>
		{/if}
	</header>

	{#if slides}
		<div class="panes">
			<ComparePane
				slideId={slides.left}
				side="left"
				restore={leftRestore}
				mark={leftMark}
				{relativeScale}
				onregister={(controller, mpp) => register('left', controller, mpp)}
				ongesture={() => gesture('left')}
				onmove={() => move('left')}
				onsettle={() => settle('left')}
			/>
			<ComparePane
				slideId={slides.right}
				side="right"
				restore={rightRestore}
				mark={rightMark}
				{relativeScale}
				onregister={(controller, mpp) => register('right', controller, mpp)}
				ongesture={() => gesture('right')}
				onmove={() => move('right')}
				onsettle={() => settle('right')}
			/>
		</div>
	{:else}
		<div class="missing" data-state="missing-parameters">
			<EmptyState icon="search" title={MISSING_COMPARE_TITLE} description={MISSING_COMPARE_BODY} />
			<p class="hint">
				<code>{missingCompareHint()}</code>
			</p>
			<Typography as="p" style="small" tone="secondary">
				Add <code>lx</code>, <code>ly</code>, <code>lzoom</code> and <code>rx</code>,
				<code>ry</code>,
				<code>rzoom</code> to open each slide at a level-0 location. <code>sync=0</code> starts the panes
				unlinked.
			</Typography>
		</div>
	{/if}
</div>

<style>
	.compare-page {
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		height: calc(100dvh - var(--header-height) - var(--notice-height));
		min-height: 28rem;
		background: var(--color-canvas);
	}
	.compare-bar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-3) var(--space-4);
		border-bottom: var(--border-width) solid var(--color-border);
		background: var(--color-surface);
	}
	.bar-copy {
		display: grid;
		gap: var(--space-1);
		min-width: 0;
	}
	.sync {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-shrink: 0;
	}
	.panes {
		display: grid;
		grid-template-columns: 1fr 1fr;
		min-height: 0;
	}
	.missing {
		display: grid;
		align-content: center;
		justify-items: center;
		gap: var(--space-2);
		padding: var(--space-8);
		text-align: center;
	}
	.hint {
		margin: 0;
	}
	.hint code,
	.missing :global(code) {
		font: var(--font-mono);
	}
	@media (max-width: 800px) {
		.compare-page {
			height: auto;
			min-height: calc(100dvh - var(--header-height) - var(--notice-height));
		}
		.compare-bar {
			align-items: flex-start;
			flex-direction: column;
		}
		.panes {
			grid-template-columns: 1fr;
			grid-template-rows: minmax(22rem, 50dvh) minmax(22rem, 50dvh);
		}
	}
</style>
