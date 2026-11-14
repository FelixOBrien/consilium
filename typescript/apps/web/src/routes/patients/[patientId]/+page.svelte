<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		Avatar,
		Badge,
		Button,
		EmptyState,
		Icon,
		SegmentedControl,
		Skeleton,
		StateMessage,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import {
		fetchPatient,
		isNotFound,
		PatientRequestError,
		searchPatientReports,
		searchPatientTissue
	} from '#lib/patients/load.js';
	import {
		corpusSearchHref,
		presentPatient,
		presentSearchHits,
		presentTimeline,
		SYNTHETIC_PATIENT_LINKAGE
	} from '#lib/patients/present.js';
	import {
		parsePatientSearch,
		writePatientSearch,
		type PatientSearchQuery
	} from '#lib/patients/query.js';
	import { patientRecordScreen, patientSearchScreen } from '#lib/patients/screen.js';
	import type { CaseHit } from '#lib/patients/load.js';
	import type { PatientDetail, PatientSearchMode, PeekPatch } from '#lib/patients/types.js';

	const productName = 'Consilium'; // pragma: allowlist secret
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let detail = $state<PatientDetail | null>(null);
	let patientLoading = $state(true);
	let notFound = $state(false);
	let patientError = $state<string | null>(null);
	let patientNonce = $state(0);
	let hits = $state<CaseHit[]>([]);
	let notice = $state<string | null>(null);
	let searchLoading = $state(false);
	let searchFailed = $state(false);
	let searchError = $state('This search could not run.');
	let searchNonce = $state(0);
	// Edited locally, then committed to `q` on submit. Not a mirror of the URL.
	// eslint-disable-next-line svelte/prefer-writable-derived -- the field stays editable until search is submitted
	let draft = $state('');
	// eslint-disable-next-line svelte/prefer-writable-derived -- mode can change before a query is submitted
	let mode = $state<PatientSearchMode>('reports');
	let patientToken = 0;
	let searchToken = 0;

	const patientId = $derived(data.patientId);
	const search = $derived(parsePatientSearch(page.url.searchParams));
	const record = $derived(
		patientRecordScreen({
			loading: patientLoading,
			notFound,
			failed: patientError !== null
		})
	);
	const header = $derived(detail ? presentPatient(detail) : null);
	const timeline = $derived(detail ? presentTimeline(detail) : []);
	const results = $derived(presentSearchHits(patientId, search.mode, hits));
	const thumbByCase = $derived(
		new Map(timeline.map((item) => [item.id, item.thumbnailUrl] as const))
	);
	const resultsScreen = $derived(
		patientSearchScreen({
			active: search.q.length > 0,
			loading: searchLoading,
			failed: searchFailed,
			hitCount: results.length
		})
	);

	$effect(() => {
		draft = search.q;
	});

	$effect(() => {
		mode = search.mode;
	});

	$effect(() => {
		const id = patientId;
		void patientNonce;
		const token = ++patientToken;
		patientLoading = true;
		notFound = false;
		patientError = null;
		detail = null;
		void loadRecord(id, token);
	});

	$effect(() => {
		const id = patientId;
		const query = search.q;
		const searchMode = search.mode;
		void searchNonce;
		if (!query) {
			hits = [];
			notice = null;
			searchLoading = false;
			searchFailed = false;
			return;
		}
		const token = ++searchToken;
		searchLoading = true;
		searchFailed = false;
		hits = [];
		notice = null;
		void loadSearch(id, query, searchMode, token);
	});

	function commitSearch(next: PatientSearchQuery) {
		const url = writePatientSearch(new URL(page.url.href), next);
		const target = `${url.pathname}${url.search}`;
		const current = `${page.url.pathname}${page.url.search}`;
		if (target === current) {
			searchNonce += 1;
			return;
		}
		void goto(resolve(target as '/'), { replace: true, reset: false });
	}

	function submitSearch(event: SubmitEvent) {
		event.preventDefault();
		commitSearch({ q: draft.trim(), mode });
	}

	function onMode(value: string) {
		const next: PatientSearchMode = value === 'tissue' ? 'tissue' : 'reports';
		mode = next;
		if (!search.q) return;
		commitSearch({ q: search.q, mode: next });
	}

	function clearSearch() {
		draft = '';
		commitSearch({ q: '', mode: 'reports' });
	}

	function retryPatient() {
		patientNonce += 1;
	}

	function retrySearch() {
		searchNonce += 1;
	}

	function peek(caseId: string, patch?: PeekPatch | null) {
		casePeek.open(patch ? { caseId, patch } : { caseId });
	}

	async function loadRecord(id: string, token: number) {
		try {
			const next = await fetchPatient(id);
			if (token !== patientToken) return;
			detail = next;
			patientLoading = false;
		} catch (error) {
			if (token !== patientToken) return;
			detail = null;
			patientLoading = false;
			if (isNotFound(error)) {
				notFound = true;
				return;
			}
			patientError =
				error instanceof PatientRequestError
					? error.message
					: 'Check the connection and try again.';
		}
	}

	async function loadSearch(
		id: string,
		query: string,
		searchMode: PatientSearchMode,
		token: number
	) {
		try {
			const result =
				searchMode === 'tissue'
					? await searchPatientTissue(id, query)
					: await searchPatientReports(id, query);
			if (token !== searchToken) return;
			hits = result.hits;
			notice = result.notice;
			searchLoading = false;
		} catch (error) {
			if (token !== searchToken) return;
			hits = [];
			notice = null;
			searchLoading = false;
			searchFailed = true;
			searchError =
				error instanceof PatientRequestError
					? error.message
					: 'Check the connection and try again.';
		}
	}
</script>

<svelte:head>
	<title>{header?.displayLabel ?? patientId} · Patient · {productName}</title>
</svelte:head>

<div class="page patient-page">
	{#if record === 'loading'}
		<section class="surface loading-wrap" aria-busy="true">
			<Skeleton width="short" height="lg" />
			<Skeleton width="medium" />
			<Skeleton height="xl" />
			<Skeleton height="xl" />
		</section>
	{:else if record === 'error'}
		<StateMessage
			tone="danger"
			title="The patient record could not be loaded"
			description={patientError ?? 'Check the connection and try again.'}
			action="Retry"
			onaction={retryPatient}
		/>
	{:else if record === 'not-found' || !header}
		<section class="surface missing">
			<EmptyState
				icon="warning"
				title="Patient not found"
				description="No patient with this identifier is in the cohort."
			/>
			<div class="missing-actions">
				<Button href="/patients" variant="primary">Patient directory</Button>
				<Button href="/" variant="secondary">Worklist</Button>
			</div>
		</section>
	{:else}
		<div class="page-heading">
			<div class="heading-copy">
				<Typography as="span" style="eyebrow" tone="accent">Patient record</Typography>
				<div class="title-row">
					<Typography as="h1" style="display">{header.displayLabel}</Typography>
					{#if header.syntheticLinkage}
						<Badge tone="synthetic">{SYNTHETIC_PATIENT_LINKAGE}</Badge>
					{/if}
				</div>
				<Typography tone="secondary">
					Sex {header.sex} · {header.birthYear} · Specialties: {header.specialties}
				</Typography>
				{#if header.syntheticLinkage}
					<Typography style="small" tone="secondary">
						This longitudinal record links more than one de-identified donor. The pairing is
						synthetic.
					</Typography>
				{/if}
			</div>
			<div class="header-actions">
				<Button href="/patients" variant="secondary" icon="arrow-left">All patients</Button>
				<Button href="/" variant="ghost">Worklist</Button>
			</div>
		</div>

		<div class="summary-grid">
			<div class="surface stat">
				<Typography style="title">{header.caseCount}</Typography>
				<Typography style="small" tone="muted">Total cases</Typography>
			</div>
			<div class="surface stat">
				<Typography style="title">{header.openCount}</Typography>
				<Typography style="small" tone="muted">Open</Typography>
			</div>
			<div class="surface stat">
				<Typography style="title">{header.signedOutCount}</Typography>
				<Typography style="small" tone="muted">Signed out</Typography>
			</div>
		</div>

		<section class="surface patient-search">
			<div class="search-head">
				<div>
					<Typography as="h2" style="section">Search this patient's cases</Typography>
					<Typography style="small" tone="secondary">
						Signed-out cases of {header.displayLabel} only. Open cases are excluded.
					</Typography>
				</div>
				<SegmentedControl
					bind:value={mode}
					onchange={onMode}
					items={[
						{ label: 'Reports', value: 'reports' },
						{ label: 'Tissue', value: 'tissue' }
					]}
				/>
			</div>
			<form class="search-bar" onsubmit={submitSearch}>
				<TextField
					bind:value={draft}
					icon={mode === 'reports' ? 'report' : 'evidence'}
					placeholder={mode === 'reports'
						? `Search signed-out reports for ${header.displayLabel}…`
						: `Describe tissue in ${header.displayLabel}'s slides…`}
					name="q"
					type="search"
				/>
				<Button type="submit" variant="primary">Search</Button>
				{#if search.q || draft.trim()}
					<Button type="button" variant="ghost" icon="close" onclick={clearSearch}>Clear</Button>
				{/if}
			</form>
		</section>

		{#if resultsScreen === 'loading'}
			<section class="surface loading-wrap" aria-busy="true">
				<Skeleton width="medium" />
				<Skeleton height="xl" />
			</section>
		{:else if resultsScreen === 'error'}
			<StateMessage
				tone="danger"
				title="This search could not run"
				description={searchError}
				action="Retry"
				onaction={retrySearch}
			/>
		{:else if resultsScreen === 'empty'}
			<section class="surface">
				<EmptyState
					icon="search"
					title="No signed-out cases for this patient matched"
					description="Clear the query to see the full timeline, or search across all patients."
					action="Clear patient query"
					onaction={clearSearch}
				/>
				<div class="missing-actions">
					<Button href={corpusSearchHref(search.q, search.mode)} variant="secondary">
						Search all patients
					</Button>
				</div>
			</section>
		{:else if resultsScreen === 'results'}
			<section class="surface results-surface">
				<header class="timeline-header">
					<div>
						<Typography as="h2" style="section">
							Patient search results ({results.length})
						</Typography>
						<Typography style="small" tone="muted">
							{search.mode === 'reports' ? 'Reports' : 'Tissue'} · {header.displayLabel} · “{search.q}”
						</Typography>
						{#if notice}
							<Typography style="small" tone="secondary">{notice}</Typography>
						{/if}
					</div>
				</header>
				<div class="timeline-list">
					{#each results as hit (hit.caseId)}
						{@const thumb = thumbByCase.get(hit.caseId)}
						<article class="case-card" data-case-id={hit.caseId} data-status="signed_out">
							{#if hit.patches.length > 0}
								<div class="patch-strip">
									{#each hit.patches as patch (patch.id)}
										<button
											type="button"
											class="thumb-button"
											aria-label={`Peek patch ${patch.id} of ${hit.caseId}`}
											onclick={() => peek(hit.caseId, patch.peek)}
										>
											<TissueImage
												src={patch.thumbnailUrl}
												alt={`Matched patch ${patch.id} for ${hit.caseId}`}
												size="md"
											/>
										</button>
									{/each}
								</div>
							{:else if thumb}
								<TissueImage src={thumb} alt={`Slide thumbnail for ${hit.caseId}`} size="lg" />
							{/if}
							<div class="case-body">
								<div class="case-top">
									<div>
										<Typography as="h3" style="subsection">{hit.caseId}</Typography>
										<Typography style="small" tone="secondary">
											{hit.specimenLabel} · {hit.specialtyLabel} · {hit.accessioned}
										</Typography>
									</div>
									<div class="badges">
										<Badge tone="success">Signed out</Badge>
										{#if hit.icd10}
											<Badge tone="neutral">{hit.icd10}</Badge>
										{/if}
									</div>
								</div>
								{#if hit.passage}
									<div class="passage">
										<Typography style="eyebrow" tone="muted">{hit.passage.sectionLabel}</Typography>
										<Typography>
											{#each hit.passage.segments as segment, index (index)}
												{#if segment.highlighted}
													<mark>{segment.text}</mark>
												{:else}
													{segment.text}
												{/if}
											{/each}
										</Typography>
									</div>
								{:else if search.mode === 'reports'}
									<Typography style="small" tone="secondary">
										No highlighted passage was returned for this case.
									</Typography>
								{:else if hit.patches.length === 0}
									<Typography style="small" tone="secondary">
										No matching patch thumbnail was returned.
									</Typography>
								{/if}
								<div class="case-footer">
									<div class="author">
										<Avatar name={hit.authorName} size="sm" />
										<Button href={hit.authorHref} variant="ghost" size="sm">
											{hit.authorName}
										</Button>
										{#if hit.authorSynthetic}
											<Badge tone="synthetic">Synthetic</Badge>
										{/if}
									</div>
									<div class="actions">
										<Button
											variant="secondary"
											size="sm"
											onclick={() => peek(hit.caseId, hit.peekPatch)}
										>
											Peek
										</Button>
										<Button href={hit.openHref} variant="primary" size="sm" icon="external">
											Open case
										</Button>
									</div>
								</div>
							</div>
						</article>
					{/each}
				</div>
			</section>
		{:else}
			<section class="surface timeline-surface">
				<header class="timeline-header">
					<div>
						<Typography as="h2" style="section">Chronological case timeline</Typography>
						<Typography style="small" tone="muted">{header.timelineNote}</Typography>
					</div>
				</header>
				<div class="timeline-list">
					{#each timeline as item (item.id)}
						<article class="case-card" data-case-id={item.id} data-status={item.status}>
							{#if item.thumbnailUrl}
								<TissueImage
									src={item.thumbnailUrl}
									alt={`Slide thumbnail for ${item.id}`}
									size="lg"
								/>
							{:else}
								<div class="thumb-fallback">
									<Typography style="small" tone="muted">No slide thumbnail</Typography>
								</div>
							{/if}
							<div class="case-body">
								<div class="case-top">
									<div>
										<Typography as="h3" style="subsection">{item.id}</Typography>
										<Typography style="small" tone="secondary">
											{item.specimenLabel} · {item.specialtyLabel} · {item.ageAtAccession} ·
											{item.slideLabel} · {item.accessioned}
										</Typography>
									</div>
									<div class="badges">
										<Badge tone={item.status === 'open' ? 'warning' : 'success'}>
											{item.statusLabel}
										</Badge>
										{#if item.status === 'signed_out' && item.icd10}
											<Badge tone="neutral">{item.icd10}</Badge>
										{/if}
									</div>
								</div>

								{#if item.status === 'signed_out' && item.conclusion}
									<Typography>{item.conclusion}</Typography>
								{:else if item.status === 'open'}
									<div class="open-notice">
										<Icon name="warning" size="sm" />
										<Typography style="small" tone="secondary">
											Not yet reported. Report text and diagnosis codes stay hidden until sign-out.
										</Typography>
									</div>
								{/if}

								<div class="case-footer">
									<div class="author">
										<Avatar name={item.pathologistName} size="sm" />
										<Typography style="small">{item.pathologistRole}</Typography>
										<Button href={item.pathologistHref} variant="ghost" size="sm">
											{item.pathologistName}
										</Button>
										{#if item.pathologistSynthetic}
											<Badge tone="synthetic">Synthetic</Badge>
										{/if}
									</div>
									<div class="actions">
										<Button variant="secondary" size="sm" onclick={() => peek(item.id)}>Peek</Button
										>
										{#if item.consultHref}
											<Button href={item.consultHref} variant="secondary" size="sm" icon="spark">
												Consult with history
											</Button>
										{/if}
										<Button href={item.openHref} variant="primary" size="sm" icon="external">
											Open case
										</Button>
									</div>
								</div>
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/if}
	{/if}
</div>

<style>
	.patient-page {
		display: grid;
		gap: var(--space-5);
		max-width: 82rem;
	}
	.title-row,
	.header-actions,
	.badges,
	.author,
	.actions,
	.patch-strip,
	.missing-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.missing-actions {
		justify-content: center;
		padding: 0 var(--space-6) var(--space-6);
	}
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: var(--space-3);
	}
	.stat {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-4);
	}
	.patient-search {
		display: grid;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.search-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
	}
	.search-head > div {
		display: grid;
		gap: var(--space-1);
	}
	.search-bar {
		display: grid;
		grid-template-columns: 1fr auto auto;
		gap: var(--space-3);
	}
	.timeline-surface,
	.results-surface {
		overflow: hidden;
	}
	.timeline-header {
		padding: var(--space-5);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.timeline-header > div {
		display: grid;
		gap: var(--space-1);
	}
	.timeline-list {
		display: grid;
	}
	.case-card {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-4);
		padding: var(--space-5);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.case-card:last-child {
		border-bottom: 0;
	}
	.case-body {
		display: grid;
		gap: var(--space-3);
		min-width: 0;
	}
	.case-top,
	.case-footer {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.case-top > div:first-child {
		display: grid;
		gap: var(--space-1);
	}
	.passage {
		display: grid;
		gap: var(--space-1);
		padding: var(--space-3);
		border-left: 0.1875rem solid var(--color-action);
		border-radius: 0 var(--radius-md) var(--radius-md) 0;
		background: var(--color-surface-raised);
	}
	.passage :global(mark) {
		background: var(--color-action-soft);
		color: inherit;
		padding: 0 0.12em;
		border-radius: 0.15em;
	}
	.open-notice {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-warning-soft);
	}
	.thumb-button {
		padding: 0;
		border: 0;
		background: transparent;
		cursor: pointer;
		border-radius: var(--radius-sm);
	}
	.thumb-button:focus-visible {
		outline: 2px solid var(--color-action);
		outline-offset: 2px;
	}
	.thumb-fallback {
		display: grid;
		place-items: center;
		width: var(--thumb-lg);
		height: var(--thumb-lg);
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-image-placeholder);
		text-align: center;
	}
	.loading-wrap {
		display: grid;
		gap: var(--space-4);
		padding: var(--space-6);
	}
	@media (max-width: 760px) {
		.summary-grid,
		.case-card {
			grid-template-columns: 1fr;
		}
		.search-head,
		.case-top,
		.case-footer,
		.search-bar {
			grid-template-columns: 1fr;
			flex-direction: column;
			align-items: stretch;
		}
	}
</style>
