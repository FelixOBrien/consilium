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
		SelectField,
		Skeleton,
		StateMessage,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import { identity } from '#lib/identity/identity.svelte.js';
	import HighlightedText from '#lib/search/HighlightedText.svelte';
	import { runSearch } from '#lib/search/load.js';
	import {
		exactBadge,
		openHref,
		patchThumbnail,
		peekTarget,
		presentHit,
		resultSummary,
		type PatchHit,
		type PresentedHit
	} from '#lib/search/present.js';
	import {
		hasSearchFilters,
		parseSearchQuery,
		searchHref,
		searchQueryKey,
		type CaseHit,
		type SearchMode,
		type SearchQuery
	} from '#lib/search/query.js';
	import { searchScreen } from '#lib/search/screen.js';
	import IcdPrefixField from '#lib/worklist/IcdPrefixField.svelte';
	import {
		CASE_STATUSES,
		SPECIALTIES,
		specialtyLabel,
		statusLabel,
		type CaseStatus
	} from '#lib/worklist/query.js';

	const statusOptions = [
		{ value: '', label: 'Any status' },
		...CASE_STATUSES.map((status) => ({ value: status, label: statusLabel(status) }))
	];
	const specialtyOptions = [
		{ value: '', label: 'All specialties' },
		...SPECIALTIES.map((specialty) => ({ value: specialty, label: specialtyLabel(specialty) }))
	];

	let draft = $state('');
	let draftSeen = '';
	let hits = $state<CaseHit[]>([]);
	let searching = $state(false);
	let failed = $state(false);
	let errorMessage = $state('Search failed. The query and filters are unchanged.');
	let notice = $state<string | null>(null);
	let tookMs = $state(0);
	let attempt = $state(0);
	let requestId = 0;
	let shownKey = '';

	const search = $derived(parseSearchQuery(page.url.searchParams));
	const presented = $derived(hits.map((item) => presentHit(item, search.q)));
	const screen = $derived(
		searchScreen({
			hasQuery: Boolean(search.q),
			searching,
			failed,
			count: presented.length
		})
	);
	const hasFilters = $derived(hasSearchFilters(search));
	const assignedOptions = $derived([
		{ value: '', label: 'Anyone' },
		...identity.roster.map((person) => ({ value: person.id, label: person.name }))
	]);
	const patientLabel = $derived.by(() => {
		if (!search.patientId) return null;
		return (
			presented.find((item) => item.patientId === search.patientId)?.patientLabel ??
			search.patientId
		);
	});
	const emptyDescription = $derived(
		search.mode === 'reports'
			? 'Nothing in the reports matched this wording. Try Tissue mode for a description of the tissue, or remove filters.'
			: 'No tissue patches matched this description. Try Reports mode for report language, or remove filters.'
	);

	$effect(() => {
		const next = search.q;
		if (next === draftSeen) return;
		draft = next;
		draftSeen = next;
	});

	$effect(() => {
		if (search.q) return;
		void goto(resolve('/'), { replaceState: true });
	});

	$effect(() => {
		const current = search;
		const key = searchQueryKey(current);
		void attempt;
		void identity.revision;
		if (!current.q) return;
		const id = ++requestId;
		searching = true;
		failed = false;
		void execute(current, key, id);
	});

	async function execute(current: SearchQuery, key: string, id: number) {
		try {
			const result = await runSearch(current);
			if (id !== requestId) return;
			hits = result.hits;
			notice = result.notice;
			tookMs = result.tookMs;
			shownKey = key;
			searching = false;
			failed = false;
		} catch (error) {
			if (id !== requestId) return;
			searching = false;
			failed = true;
			errorMessage =
				error instanceof Error
					? error.message
					: 'Search failed. The query and filters are unchanged.';
			if (shownKey !== key) {
				hits = [];
				notice = null;
				tookMs = 0;
			}
		}
	}

	function navigate(next: SearchQuery) {
		const href = searchHref(next);
		if (href === '/') {
			void goto(resolve('/'));
			return;
		}
		const current = `${page.url.pathname}${page.url.search}`;
		if (href === current) return;
		void goto(resolve(href as '/'), { reset: false });
	}

	function submitDraft(event: SubmitEvent) {
		event.preventDefault();
		const q = draft.trim();
		if (!q) {
			void goto(resolve('/'));
			return;
		}
		navigate({ ...search, q });
	}

	function setMode(value: string) {
		const mode: SearchMode = value === 'tissue' ? 'tissue' : 'reports';
		navigate({ ...search, mode });
	}

	function setStatus(value: string) {
		const status: CaseStatus | null = value === 'open' || value === 'signed_out' ? value : null;
		navigate({ ...search, status });
	}

	function setSpecialty(value: string) {
		navigate({ ...search, specialty: SPECIALTIES.find((item) => item === value) ?? null });
	}

	function setAssigned(value: string) {
		navigate({ ...search, assignedTo: value || null });
	}

	function clearFilters() {
		navigate({
			...search,
			status: null,
			specialty: null,
			assignedTo: null,
			icd10: null,
			patientId: null
		});
	}

	function retry() {
		attempt += 1;
	}

	function openPeek(item: PresentedHit, patch?: PatchHit) {
		const chosen = patch ?? (search.mode === 'tissue' ? item.patches[0] : undefined);
		casePeek.open({
			caseId: item.id,
			patch: chosen ? peekTarget(chosen) : undefined
		});
	}

	function caseHref(item: PresentedHit, patch?: PatchHit | null) {
		return openHref(item.id, search.mode, patch ?? null);
	}
</script>

<svelte:head>
	<title>Search · Consilium</title>
</svelte:head>

<div class="page search-page" data-screen={screen} aria-busy={searching}>
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Corpus retrieval</Typography>
			<Typography as="h1" style="display">Search precedent</Typography>
			<Typography tone="secondary">
				Search signed-out cases by report language or a description of tissue. Results are retrieved
				precedent, not a diagnosis.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	{#if screen === 'redirect'}
		<Typography tone="secondary">Returning to the worklist…</Typography>
	{:else}
		<section class="surface search-surface" aria-label="Case search">
			<div class="query-region">
				<SegmentedControl
					value={search.mode}
					onchange={setMode}
					items={[
						{ label: 'Reports', value: 'reports' },
						{ label: 'Tissue', value: 'tissue' }
					]}
				/>
				<form class="query-input" onsubmit={submitDraft}>
					<TextField
						bind:value={draft}
						icon={search.mode === 'reports' ? 'report' : 'evidence'}
						placeholder={search.mode === 'reports'
							? 'Search report language, case ID or ICD-10…'
							: 'Describe tissue morphology…'}
					/>
					<Button type="submit" variant="primary" icon="search">Search</Button>
				</form>
				<Typography style="small" tone="muted">
					{search.mode === 'reports'
						? 'Hybrid keyword and semantic retrieval across signed reports. An exact case ID or ICD-10 code is listed first.'
						: 'The description is matched to stored tissue patch embeddings.'}
				</Typography>
			</div>

			<div class="toolbar">
				<SelectField
					value={search.status ?? ''}
					onchange={setStatus}
					compact
					label="Status"
					options={statusOptions}
				/>
				<SelectField
					value={search.specialty ?? ''}
					onchange={setSpecialty}
					compact
					label="Specialty"
					options={specialtyOptions}
				/>
				<SelectField
					value={search.assignedTo ?? ''}
					onchange={setAssigned}
					compact
					label="Pathologist"
					options={assignedOptions}
				/>
				<IcdPrefixField
					value={search.icd10 ?? ''}
					onchange={(icd10) => navigate({ ...search, icd10 })}
				/>
				{#if search.patientId}
					<button
						class="chip"
						type="button"
						onclick={() => navigate({ ...search, patientId: null })}
					>
						Patient {patientLabel}
						<Icon name="close" size="sm" />
					</button>
				{/if}
				<div class="spacer"></div>
				{#if hasFilters}
					<Button variant="ghost" size="sm" icon="close" onclick={clearFilters}>
						Remove filters
					</Button>
				{/if}
				<Button variant="ghost" size="sm" icon="close" onclick={() => goto(resolve('/'))}>
					Clear query
				</Button>
			</div>

			{#if notice}
				<div class="state-wrap">
					<StateMessage tone="info" title="Search notice" description={notice} />
				</div>
			{/if}

			{#if screen === 'error'}
				<div class="state-wrap">
					<StateMessage
						tone="danger"
						title="Search failed"
						description={errorMessage}
						action="Retry"
						onaction={retry}
					/>
				</div>
			{:else if screen === 'loading'}
				<div class="result-list" aria-busy="true">
					{#each [0, 1, 2, 3] as row (row)}
						<div class="result-card loading">
							<Skeleton height="xl" width="short" />
							<div><Skeleton width="medium" /><Skeleton /><Skeleton height="sm" /></div>
							<Skeleton height="lg" />
						</div>
					{/each}
				</div>
			{:else if screen === 'empty'}
				<EmptyState
					title="No cases matched"
					description={emptyDescription}
					action={search.mode === 'reports' ? 'Try Tissue mode' : 'Try Reports mode'}
					onaction={() => setMode(search.mode === 'reports' ? 'tissue' : 'reports')}
				/>
				{#if hasFilters}
					<div class="empty-extra">
						<Button variant="ghost" onclick={clearFilters}>Remove filters</Button>
					</div>
				{/if}
			{:else}
				{#if searching}
					<div class="state-wrap">
						<StateMessage
							tone="info"
							title="Searching"
							description="Previous results stay visible and may not match the latest query."
						/>
					</div>
				{/if}
				{#if failed}
					<div class="state-wrap">
						<StateMessage
							tone="danger"
							title="Search failed"
							description={errorMessage}
							action="Retry"
							onaction={retry}
						/>
					</div>
				{/if}
				<div class="results-heading">
					<div>
						<Typography as="h2" style="section">Matching cases</Typography>
						{#if !searching}
							<Typography style="small" tone="secondary">
								{resultSummary(presented.length, tookMs)}. Relative match only, within this result
								list.
							</Typography>
						{/if}
					</div>
				</div>

				<div class="result-list" class:stale={searching}>
					{#each presented as item, index (item.id)}
						<article
							class="result-card"
							data-case={item.id}
							data-status={item.status}
							data-exact={item.exact ?? 'none'}
							data-match={item.matchLabel ?? 'none'}
						>
							<div class="rank" aria-hidden="true">{index + 1}</div>
							<div class="result-main">
								<div class="result-title">
									<div>
										<Typography as="h3" style="subsection">{item.id}</Typography>
										<div class="meta-row">
											<a
												class="patient-link"
												href={resolve('/patients/[patientId]', { patientId: item.patientId })}
											>
												{item.patientLabel}
											</a>
											{#if item.patientCaseCount > 1}
												<Typography style="small" tone="muted">
													{item.patientCaseCount} cases
												</Typography>
											{/if}
											<Typography style="small" tone="secondary">
												{item.specialtyLabel} · {item.ageSex}
											</Typography>
											{#if item.open}
												<Badge tone="warning">Open</Badge>
											{/if}
											{#if item.icd10}
												<Badge tone="neutral">{item.icd10}</Badge>
											{/if}
											{#if exactBadge(item.exact)}
												<Badge tone="warning">{exactBadge(item.exact)}</Badge>
											{/if}
											{#if item.matchLabel}
												<Badge tone={item.matchLabel === 'Meaning' ? 'accent' : 'info'}>
													{item.matchLabel}
												</Badge>
											{/if}
										</div>
									</div>
									<div class="score">
										<Typography style="eyebrow" tone="muted">Relative match</Typography>
										<div class="score-track" aria-hidden="true">
											<span style:--score={item.score}></span>
										</div>
									</div>
								</div>

								{#if item.open}
									<div class="open-note">
										<Typography style="small" tone="secondary">
											Open case. Report text, conclusion and ICD-10 are not shown.
										</Typography>
									</div>
								{:else if search.mode === 'reports' && item.passage}
									<div class="passage">
										<Typography style="eyebrow" tone="muted">{item.passage.sectionLabel}</Typography
										>
										<Typography>
											<HighlightedText
												text={item.passage.text}
												highlights={item.passage.highlights}
											/>
										</Typography>
									</div>
								{:else if search.mode === 'reports'}
									<Typography style="small" tone="muted"
										>No matching passage was returned.</Typography
									>
								{:else}
									<div class="patches">
										{#each item.patches as patch (patch.patch_id)}
											<a
												class="patch-link"
												href={resolve(openHref(item.id, 'tissue', patch) as '/')}
												aria-label={`Open ${item.id} centred on this patch`}
											>
												<TissueImage
													src={patchThumbnail(patch)}
													alt={`Matching tissue patch from ${item.id}`}
													size="lg"
												/>
											</a>
										{/each}
										<div class="patch-summary">
											<Typography style="label">
												{item.patchCount}
												{item.patchCount === 1 ? 'matching patch' : 'matching patches'}
											</Typography>
											{#if item.conclusion}
												<Typography style="small" tone="secondary">{item.conclusion}</Typography>
											{/if}
										</div>
									</div>
								{/if}

								<div class="result-footer">
									<div class="author">
										<Avatar name={item.authorName} size="sm" />
										<Typography style="small">{item.authorName}</Typography>
										{#if item.authorSynthetic}
											<Badge tone="synthetic">Synthetic</Badge>
										{/if}
									</div>
									<div class="result-actions">
										<Button variant="secondary" size="sm" onclick={() => openPeek(item)}
											>Peek</Button
										>
										<Button
											href={caseHref(
												item,
												search.mode === 'tissue' ? (item.patches[0] ?? null) : null
											)}
											variant="primary"
											size="sm"
											icon="external"
										>
											Open case
										</Button>
									</div>
								</div>
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</section>
	{/if}
</div>

<style>
	.search-page {
		max-width: 80rem;
	}
	.search-surface {
		overflow: hidden;
	}
	.query-region {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-6);
		background:
			linear-gradient(110deg, var(--color-action-soft), transparent 48%), var(--color-surface);
	}
	.query-input {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-3);
	}
	.toolbar :global(.field) {
		min-width: 11rem;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		align-self: end;
		min-height: var(--control-md);
		padding: 0 var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-pill);
		background: var(--color-action-soft);
		color: var(--color-action);
		font: var(--font-label-sm);
		cursor: pointer;
	}
	.results-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-5) var(--space-6) var(--space-3);
	}
	.results-heading > div {
		display: grid;
		gap: var(--space-1);
	}
	.result-list {
		display: grid;
		padding: 0 var(--space-6) var(--space-6);
	}
	.result-list.stale {
		opacity: 0.62;
	}
	.result-card {
		display: grid;
		grid-template-columns: 2.5rem 1fr;
		gap: var(--space-4);
		padding: var(--space-5) 0;
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.result-card:last-child {
		border-bottom: 0;
	}
	.result-card.loading {
		grid-template-columns: 6rem 1fr 8rem;
	}
	.result-card.loading > div {
		display: grid;
		gap: var(--space-2);
	}
	.rank {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
	}
	.result-main,
	.result-title {
		display: grid;
		gap: var(--space-4);
	}
	.result-title {
		grid-template-columns: 1fr 10rem;
	}
	.result-title > div:first-child,
	.passage {
		display: grid;
		gap: var(--space-2);
	}
	.patient-link {
		color: var(--color-action);
		font: var(--font-label-sm);
		text-decoration: none;
	}
	.patient-link:hover {
		text-decoration: underline;
	}
	.score {
		display: grid;
		align-content: start;
		gap: var(--space-2);
		text-align: right;
	}
	.score-track {
		height: var(--space-2);
		overflow: hidden;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
	}
	.score-track span {
		display: block;
		width: calc(var(--score) * 100%);
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, var(--color-action), var(--color-score-end));
	}
	.passage,
	.open-note {
		padding: var(--space-4);
		border-left: 0.1875rem solid var(--color-action);
		border-radius: 0 var(--radius-md) var(--radius-md) 0;
		background: var(--color-surface-raised);
	}
	.open-note {
		border-left-color: var(--color-border-strong);
	}
	.patches {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		align-items: center;
	}
	.patch-link {
		display: block;
		border-radius: var(--radius-sm);
		line-height: 0;
	}
	.patch-link:focus-visible {
		outline: 0.125rem solid var(--color-action);
		outline-offset: 0.125rem;
	}
	.patch-summary {
		display: grid;
		gap: var(--space-2);
		min-width: 12rem;
		padding-left: var(--space-3);
	}
	.result-footer,
	.author,
	.result-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.result-footer {
		justify-content: space-between;
	}
	.state-wrap,
	.empty-extra {
		padding: 0 var(--space-6) var(--space-4);
	}
	.empty-extra {
		display: flex;
		justify-content: center;
		margin-top: calc(var(--space-4) * -1);
		padding-bottom: var(--space-6);
	}
	@media (max-width: 760px) {
		.query-input {
			grid-template-columns: 1fr;
		}
		.result-title {
			grid-template-columns: 1fr;
		}
		.score {
			text-align: left;
		}
		.result-footer {
			align-items: flex-start;
			flex-direction: column;
		}
	}
</style>
