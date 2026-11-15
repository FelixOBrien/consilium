<script lang="ts">
	import { resolve } from '$app/paths';
	import {
		Badge,
		Button,
		CheckField,
		EmptyState,
		SegmentedControl,
		SelectField,
		Skeleton,
		StateMessage,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import { SPECIALTIES, specialtyLabel } from '#lib/worklist/query.js';
	import {
		consultCaseIds,
		filtersActive,
		parseSpecialty,
		patchThumbnailUrl,
		presentCase,
		presentQuery,
		presentRegions,
		type ActiveQuery,
		type EvidenceFilters,
		searchMarkers,
		type PresentedCase,
		type PresentedScore
	} from './evidence-model.js';
	import { evidenceSessionFor } from './evidence-session.js';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	const session = evidenceSessionFor(caseState.caseId);

	let tick = $state(0);
	let mode = $state(session.mode === 'reports' ? 'reports' : 'tissue');
	let draft = $state(session.draft);
	let scope = $state(session.scope === 'slide' ? 'slide' : 'corpus');
	let specialtyValue = $state(session.filters.specialty ?? '');
	let icd10 = $state(session.filters.icd10Prefix);
	let samePatient = $state(session.filters.samePatient);
	let seenSeq = session.consumedSeq;

	const specialtyOptions = [
		{ value: '', label: 'Any specialty' },
		...SPECIALTIES.map((item) => ({ value: item, label: specialtyLabel(item) }))
	];

	const view = $derived.by(() => {
		void tick;
		return {
			phase: session.phase,
			searching: session.searching,
			warming: session.warming,
			query: session.query,
			failure: session.failure,
			notice: session.notice,
			scopeNote: session.scopeNote,
			hits: session.visibleHits.map(presentCase),
			regions: session.regions ? presentRegions(session.regions.patches) : [],
			footer: session.footer,
			stale: session.searching && session.hasRows,
			hasRows: session.hasRows,
			consultIds: consultCaseIds(session.visibleHits),
			filtersActive: filtersActive(session.filters)
		};
	});

	$effect(() => {
		return session.subscribe(() => {
			tick += 1;
		});
	});

	$effect(() => {
		session.setMode(mode === 'reports' ? 'reports' : 'tissue');
	});

	$effect(() => {
		session.setDraft(draft);
	});

	$effect(() => {
		void tick;
		if (session.consumedSeq === seenSeq) return;
		seenSeq = session.consumedSeq;
		mode = session.mode;
		draft = session.draft;
		scope = session.scope;
	});

	$effect(() => {
		const next: EvidenceFilters = {
			specialty: parseSpecialty(specialtyValue),
			icd10Prefix: icd10,
			samePatient
		};
		const patientId = caseState.caseDetail?.patient.id ?? null;
		const handle = window.setTimeout(() => {
			void session.setFilters(next, patientId);
		}, 300);
		return () => window.clearTimeout(handle);
	});

	$effect(() => {
		const intent = caseState.pendingEvidenceIntent;
		if (!intent || intent.seq === session.consumedSeq) return;
		void session.runIntent(intent, intent.seq, caseState.caseDetail?.patient.id ?? null);
	});

	$effect(() => {
		void tick;
		const patches = session.regions?.patches ?? [];
		const showMarkers =
			!session.searching &&
			session.scope === 'slide' &&
			session.query != null &&
			patches.length > 0 &&
			patches[0]?.slide_id === caseState.activeSlideId;
		if (!showMarkers) {
			caseState.setSearchHitMarkers([]);
			caseState.onSearchHitClick = null;
			return;
		}
		caseState.setSearchHitMarkers(searchMarkers(patches));
		caseState.onSearchHitClick = (hit) => {
			const patch = patches.find((item) => String(item.patch_id) === hit.id);
			if (!patch) return;
			const region = presentRegions([patch])[0];
			if (region) caseState.flyToLevel0(region.fly);
		};
	});

	function patientId(): string | null {
		return caseState.caseDetail?.patient.id ?? null;
	}

	function queryImage(query: ActiveQuery): string | null {
		const presented = presentQuery(query);
		if (presented.thumbnail === 'patch' && presented.patchId) {
			return patchThumbnailUrl(presented.patchId);
		}
		if (presented.thumbnail === 'slide' && presented.slideId) {
			return (
				caseState.caseDetail?.slides.find((slide) => slide.id === presented.slideId)
					?.thumbnail_url ?? null
			);
		}
		return null;
	}

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (mode === 'reports') scope = 'corpus';
		await session.submitText(patientId());
		scope = session.scope;
	}

	async function likeSlide() {
		const slideId = caseState.activeSlideId;
		if (!slideId) return;
		mode = 'tissue';
		scope = 'corpus';
		await session.casesLikeSlide(slideId, patientId());
	}

	async function onScope(value: string) {
		await session.setScope(value === 'slide' ? 'slide' : 'corpus', patientId());
		scope = session.scope;
	}

	function clearQuery() {
		draft = '';
		scope = 'corpus';
		session.clear();
		caseState.setSearchHitMarkers([]);
		caseState.onSearchHitClick = null;
	}

	function peek(row: PresentedCase) {
		casePeek.open({ caseId: row.caseId, patch: row.peekPatch });
	}

	function openHref(row: PresentedCase): string {
		const path = resolve('/cases/[caseId]', { caseId: row.caseId });
		if (!row.openQuery) return path;
		return `${path}?${row.openQuery}`;
	}

	function sendToConsult() {
		const caseIds = consultCaseIds(session.visibleHits);
		if (caseIds.length === 0) return;
		caseState.attachToConsult({ kind: 'cases', caseIds });
	}
</script>

{#snippet score(item: PresentedScore)}
	<span
		class="score"
		role="img"
		aria-label={`Relative match: ${item.label}`}
		data-score-tier={item.tier}
	>
		<span class="score-label">{item.label}</span>
		<span class="score-track" aria-hidden="true">
			<span class="score-fill bar-{item.bar}"></span>
		</span>
	</span>
{/snippet}

<section class="evidence" data-evidence-phase={view.phase} aria-label="Evidence">
	<header class="heading">
		<div>
			<Typography style="eyebrow" tone="muted">Evidence</Typography>
			<Typography as="h2" style="section">Precedent</Typography>
		</div>
		<Badge tone="info">Not a finding</Badge>
	</header>
	<Typography style="small" tone="secondary">
		Retrieved from signed-out cases. Not a finding.
	</Typography>

	<div class="query-block" data-region="query-bar">
		<SegmentedControl
			items={[
				{ label: 'Tissue', value: 'tissue' },
				{ label: 'Reports', value: 'reports' }
			]}
			bind:value={mode}
		/>
		<form class="query-form" onsubmit={submit}>
			<TextField
				bind:value={draft}
				label={mode === 'reports' ? 'Report text' : 'Tissue description'}
				placeholder={mode === 'reports'
					? 'Search signed-out report text'
					: 'Describe a tissue pattern'}
				icon={mode === 'reports' ? 'report' : 'evidence'}
				name="evidence-query"
				compact
			/>
			<Button type="submit" variant="primary" icon="search" disabled={draft.trim() === ''}>
				Search
			</Button>
		</form>
	</div>

	{#if view.query}
		{@const presented = presentQuery(view.query)}
		{@const image = queryImage(view.query)}
		<div class="active" data-region="active-query">
			{#if image}
				<TissueImage src={image} alt="" size="md" />
			{/if}
			<div class="active-copy">
				<Typography style="eyebrow" tone="muted">{presented.kicker}</Typography>
				<Typography style="label">{presented.label}</Typography>
				{#if view.searching}
					<Typography style="small" tone="secondary">Searching signed-out cases…</Typography>
				{/if}
			</div>
			<Button variant="ghost" size="sm" icon="close" onclick={clearQuery}>Clear</Button>
		</div>
	{:else if !view.searching}
		<div class="start" data-region="starting-actions">
			<Typography style="small" tone="secondary">
				Search in three ways: select tissue or draw a region, describe a pattern, or search report
				text.
			</Typography>
			<Button
				variant="secondary"
				icon="evidence"
				disabled={!caseState.activeSlideId}
				onclick={likeSlide}
			>
				Cases like this slide
			</Button>
			<Typography style="small" tone="muted">
				Or click tissue, or draw a region, and choose Find similar tissue.
			</Typography>
		</div>
	{/if}

	{#if view.notice}
		<div data-region="notice">
			<StateMessage tone="info" title="About this query" description={view.notice} />
		</div>
	{/if}
	{#if view.warming}
		<StateMessage
			tone="info"
			title="The text encoder is warming up"
			description="The first text search can take longer than later ones. Results stay retrieved precedent."
		/>
	{/if}

	<div class="filters" data-region="filters">
		<SelectField label="Specialty" bind:value={specialtyValue} options={specialtyOptions} compact />
		<TextField
			label="ICD-10 prefix"
			bind:value={icd10}
			placeholder="C50"
			icon="search"
			name="evidence-icd10"
			compact
		/>
		<CheckField bind:checked={samePatient}>
			<Typography as="span" style="small">Same patient</Typography>
		</CheckField>
		<div class="scope">
			<Typography style="eyebrow" tone="muted">Scope</Typography>
			<SegmentedControl
				items={[
					{ label: 'All signed-out cases', value: 'corpus' },
					{ label: 'This slide', value: 'slide' }
				]}
				bind:value={scope}
				onchange={onScope}
			/>
			{#if view.scopeNote}
				<Typography style="small" tone="secondary">{view.scopeNote}</Typography>
			{/if}
		</div>
	</div>

	<div class="status" role="status" aria-live="polite">
		{#if view.failure?.kind === 'no-tissue'}
			<StateMessage
				tone="warning"
				title="Region has no tissue"
				description={view.failure.message}
			/>
		{:else if view.failure}
			<StateMessage
				tone="danger"
				title="The search failed"
				description={view.failure.message}
				action="Retry"
				onaction={() => session.retry(patientId())}
			/>
		{/if}
	</div>

	{#if view.searching && !view.hasRows}
		<div class="loading" aria-busy="true" data-region="results">
			<Skeleton height="lg" />
			<Skeleton />
			<Skeleton width="medium" />
		</div>
	{/if}

	{#if view.phase === 'empty'}
		<div data-region="results">
			<EmptyState
				icon="search"
				title="Nothing matched"
				description={view.filtersActive
					? 'Nothing matched. Remove a filter and search again.'
					: 'No signed-out case matched this search.'}
			/>
		</div>
	{/if}

	{#if view.hits.length > 0}
		<div class="results" class:stale={view.stale} data-region="results" aria-busy={view.searching}>
			<Typography style="small" tone="muted">
				Bars show relative similarity within this list. Not a finding.
			</Typography>
			<ol>
				{#each view.hits as row (row.caseId)}
					<li>
						<div class="hit-top">
							<div>
								<Typography style="label">{row.caseId}</Typography>
								<div class="meta">
									<a
										class="patient"
										href={resolve('/patients/[patientId]', { patientId: row.patientId })}
									>
										{row.patientLabel}
									</a>
									{#if row.samePatient}<Badge tone="accent">Same patient</Badge>{/if}
									{#if row.syntheticLinkage}<Badge tone="synthetic">Synthetic link</Badge>{/if}
									<Badge tone="neutral">{row.specialty}</Badge>
									{#if row.icd10}<Typography as="span" style="mono">{row.icd10}</Typography>{/if}
								</div>
							</div>
							{@render score(row.score)}
						</div>
						{#if row.conclusion}
							<Typography style="small">{row.conclusion}</Typography>
						{/if}
						<div class="meta">
							<Typography as="span" style="small" tone="secondary">
								Reported by {row.authorName}
							</Typography>
							{#if row.authorSynthetic}<Badge tone="synthetic">Synthetic</Badge>{/if}
							{#each row.matchedBy as kind (kind)}
								<Badge tone="neutral">{kind}</Badge>
							{/each}
						</div>
						{#if row.patches.length > 0}
							<div class="thumbs">
								{#each row.patches as patch (patch.patch_id)}
									<span class="thumb">
										<TissueImage src={patch.thumbnail_url} alt="Matching tissue" size="sm" />
										<span class="thumb-zoom">
											<TissueImage src={patch.thumbnail_url} alt="" size="lg" />
										</span>
									</span>
								{/each}
								{#if row.patchCountLabel}
									<Typography as="span" style="small" tone="secondary"
										>{row.patchCountLabel}</Typography
									>
								{/if}
							</div>
						{/if}
						{#if row.passage}
							<div class="passage">
								<Typography style="eyebrow" tone="muted">{row.passage.section}</Typography>
								<p>
									{#each row.passage.segments as segment, index (index)}
										{#if segment.marked}<mark>{segment.text}</mark>{:else}{segment.text}{/if}
									{/each}
								</p>
							</div>
						{/if}
						<div class="hit-actions">
							<Button variant="secondary" size="sm" onclick={() => peek(row)}>Peek</Button>
							<!-- Case path is resolve(); slide, x, y and zoom are query state. -->
							<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- query is not part of the route type -->
							<a class="open" href={openHref(row)}>Open</a>
						</div>
					</li>
				{/each}
			</ol>
			<div class="list-actions">
				<Button
					variant="primary"
					icon="send"
					disabled={view.consultIds.length === 0}
					onclick={sendToConsult}
				>
					Send results to consult
				</Button>
			</div>
		</div>
	{:else if view.regions.length > 0}
		<div class="results" class:stale={view.stale} data-region="results" aria-busy={view.searching}>
			<Typography style="small" tone="muted">
				Regions on this slide. Not a finding. Choose one to move the viewer.
			</Typography>
			<ol>
				{#each view.regions as region (region.id)}
					<li>
						<button type="button" class="region" onclick={() => caseState.flyToLevel0(region.fly)}>
							<TissueImage src={region.thumbnailUrl} alt="" size="sm" />
							<span>
								<Typography style="label">{region.label}</Typography>
								<Typography style="small" tone="secondary">{region.slideId}</Typography>
							</span>
							{@render score(region.score)}
						</button>
					</li>
				{/each}
			</ol>
		</div>
	{/if}

	{#if view.footer}
		<footer data-region="footer">
			<Typography style="small" tone="secondary">{view.footer}</Typography>
			{#if view.stale}
				<Typography style="small" tone="muted">Previous results, updating.</Typography>
			{/if}
		</footer>
	{/if}
</section>

<style>
	.evidence {
		display: grid;
		align-content: start;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.heading,
	.hit-top,
	.active,
	.meta,
	.thumbs,
	.hit-actions,
	.list-actions,
	.query-form,
	.region {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.heading,
	.hit-top,
	.active {
		justify-content: space-between;
	}
	.active-copy,
	.filters,
	.start,
	.passage,
	.results,
	.loading {
		display: grid;
		gap: var(--space-2);
		min-width: 0;
	}
	.query-block,
	.scope {
		display: grid;
		gap: var(--space-3);
	}
	.query-form {
		align-items: end;
	}
	.query-form :global(.field) {
		flex: 1;
	}
	.active {
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.filters {
		padding-top: var(--space-2);
		border-top: var(--border-width) solid var(--color-border);
	}
	.meta,
	.thumbs {
		flex-wrap: wrap;
	}
	.patient,
	.open {
		color: var(--color-action);
		font: var(--font-label-sm);
		text-decoration: none;
	}
	.patient:hover,
	.open:hover {
		text-decoration: underline;
	}
	.open {
		display: inline-flex;
		align-items: center;
		min-height: var(--control-sm);
		padding: 0 var(--space-3);
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		text-decoration: none;
	}
	.open:focus-visible,
	.region:focus-visible {
		outline: var(--focus-ring);
		outline-offset: var(--focus-offset);
	}
	.results {
		gap: var(--space-3);
	}
	.results.stale {
		opacity: 0.55;
	}
	ol {
		display: grid;
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	li {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.passage p {
		margin: 0;
		font: var(--font-small);
	}
	mark {
		padding: 0 0.12em;
		border-radius: var(--radius-sm);
		background: var(--color-warning-soft);
		color: inherit;
	}
	.thumb {
		position: relative;
	}
	.thumb-zoom {
		display: none;
		position: absolute;
		z-index: 4;
		bottom: calc(100% + var(--space-2));
		left: 0;
		padding: var(--space-1);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
	}
	.thumb:hover .thumb-zoom,
	.thumb:focus-within .thumb-zoom {
		display: block;
	}
	.region {
		width: 100%;
		padding: 0;
		border: 0;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.region > span {
		display: grid;
		flex: 1;
		gap: var(--space-1);
		min-width: 0;
	}
	.score {
		display: grid;
		justify-items: end;
		gap: var(--space-1);
		flex: none;
	}
	.score-label {
		font: var(--font-label-xs);
		color: var(--color-text-secondary);
	}
	.score-track {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		width: 4.5rem;
		height: 0.35rem;
		overflow: hidden;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
	}
	.score-fill {
		grid-column: 1 / 2;
		background: var(--color-action);
	}
	.score-fill.bar-2 {
		grid-column: 1 / 3;
	}
	.score-fill.bar-3 {
		grid-column: 1 / 4;
	}
	.score-fill.bar-4 {
		grid-column: 1 / 5;
	}
	.scope :global(.segmented) {
		display: flex;
		width: 100%;
	}
	.scope :global(.segmented button) {
		flex: 1;
		justify-content: center;
	}
	footer {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		padding-top: var(--space-2);
		border-top: var(--border-width) solid var(--color-border);
	}
</style>
