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
		TissueImage,
		Typography
	} from '#lib';
	import IcdPrefixField from '#lib/worklist/IcdPrefixField.svelte';
	import { identity } from '#lib/identity/identity.svelte.js';
	import {
		apiCaseSource,
		formatTally,
		loadFirstPage,
		loadNextPage,
		worklistTallies,
		type WorklistTallies
	} from '#lib/worklist/load.js';
	import { presentCase } from '#lib/worklist/present.js';
	import {
		CASE_STATUSES,
		SPECIALTIES,
		clearedFilters,
		hasWorklistFilters,
		parseWorklistQuery,
		specialtyLabel,
		statusLabel,
		worklistQueryKey,
		writeWorklistQuery,
		type CaseStatus,
		type CaseSummary,
		type Specialty,
		type WorklistQuery,
		type WorklistView
	} from '#lib/worklist/query.js';
	import { worklistScreen } from '#lib/worklist/screen.js';

	const source = apiCaseSource();
	const statusOptions = [
		{ value: '', label: 'Any status' },
		...CASE_STATUSES.map((status) => ({ value: status, label: statusLabel(status) }))
	];
	const specialtyOptions = [
		{ value: '', label: 'All specialties' },
		...SPECIALTIES.map((specialty) => ({ value: specialty, label: specialtyLabel(specialty) }))
	];

	let items = $state<CaseSummary[]>([]);
	let nextCursor = $state<string | null>(null);
	let loading = $state(true);
	let failed = $state(false);
	let loadingMore = $state(false);
	let moreError = $state(false);
	let tallies = $state<WorklistTallies | null>(null);
	let corpusEmpty = $state<boolean | null>(null);
	let sentinel = $state<HTMLDivElement | null>(null);
	let requestId = 0;

	const query = $derived(parseWorklistQuery(page.url.searchParams));
	const rows = $derived(items.map(presentCase));
	const assignedOptions = $derived([
		{ value: '', label: 'Anyone' },
		...identity.roster.map((person) => ({ value: person.id, label: person.name }))
	]);
	const screen = $derived(
		worklistScreen({
			loading,
			failed,
			itemCount: items.length,
			query,
			corpusEmpty,
			actingName: identity.me?.name ?? null
		})
	);
	const mineCount = $derived(formatTally(tallies?.mine));
	const allCount = $derived(formatTally(tallies?.all));
	const openCount = $derived(
		tallies ? (tallies.mine.truncated ? `${tallies.mine.open}+` : String(tallies.mine.open)) : '—'
	);
	const queueCount = $derived(mineCount ?? '—');

	$effect(() => {
		const current = query;
		const userId = identity.me?.id ?? '';
		const ready = identity.status === 'ready';
		void worklistQueryKey(current);
		void identity.revision;
		if (!ready || !userId) {
			loading = identity.status !== 'error';
			failed = identity.status === 'error';
			items = [];
			nextCursor = null;
			corpusEmpty = null;
			return;
		}
		const id = ++requestId;
		loading = true;
		failed = false;
		moreError = false;
		items = [];
		nextCursor = null;
		void refresh(current, userId, id);
	});

	$effect(() => {
		const node = sentinel;
		if (!node || !nextCursor || loading || loadingMore) return;
		const observer = new IntersectionObserver((entries) => {
			if (entries.some((entry) => entry.isIntersecting)) void loadMore();
		});
		observer.observe(node);
		return () => observer.disconnect();
	});

	function applyQuery(next: WorklistQuery) {
		const url = writeWorklistQuery(new URL(page.url.href), next);
		const target = `${url.pathname}${url.search}`;
		const current = `${page.url.pathname}${page.url.search}`;
		if (target === current) return;
		void goto(resolve(target as '/'), { reset: false });
	}

	function setView(value: string) {
		const view: WorklistView = value === 'all' ? 'all' : 'mine';
		applyQuery({ ...query, view });
	}

	function setStatus(value: string) {
		const status: CaseStatus | null = value === 'open' || value === 'signed_out' ? value : null;
		applyQuery({ ...query, status });
	}

	function setSpecialty(value: string) {
		const specialty = SPECIALTIES.find((item) => item === value) ?? null;
		applyQuery({ ...query, specialty: specialty as Specialty | null });
	}

	function setAssigned(value: string) {
		applyQuery({ ...query, assignedTo: value || null });
	}

	function clearFilters() {
		applyQuery(clearedFilters(query));
	}

	function showAllCases() {
		applyQuery({ ...clearedFilters(query), view: 'all' });
	}

	async function refresh(current: WorklistQuery, userId: string, id: number) {
		try {
			const firstPromise = loadFirstPage(source, current);
			const tallyPromise = worklistTallies(userId, source).catch(() => null);
			const first = await firstPromise;
			const nextTallies = await tallyPromise;
			if (id !== requestId) return;
			items = first.items;
			nextCursor = first.nextCursor;
			tallies = nextTallies;
			corpusEmpty = corpusIsEmpty(current, first.items.length, first.nextCursor, nextTallies);
			if (
				corpusEmpty === null &&
				first.items.length === 0 &&
				current.view === 'mine' &&
				!hasWorklistFilters(current)
			) {
				failed = true;
				corpusEmpty = null;
			}
			loading = false;
		} catch {
			if (id !== requestId) return;
			loading = false;
			failed = true;
			corpusEmpty = null;
		}
	}

	function corpusIsEmpty(
		current: WorklistQuery,
		count: number,
		cursor: string | null,
		nextTallies: WorklistTallies | null
	): boolean | null {
		if (nextTallies) return nextTallies.all.total === 0 && !nextTallies.all.truncated;
		if (current.view === 'all' && !hasWorklistFilters(current)) return count === 0 && !cursor;
		if (count === 0 && current.view === 'mine' && !hasWorklistFilters(current)) return null;
		return false;
	}

	async function loadMore() {
		if (!nextCursor || loadingMore || loading || failed) return;
		const cursor = nextCursor;
		const current = query;
		const id = requestId;
		loadingMore = true;
		moreError = false;
		try {
			const next = await loadNextPage(source, current, cursor, items);
			if (id !== requestId) return;
			items = next.items;
			nextCursor = next.nextCursor;
		} catch {
			if (id !== requestId) return;
			moreError = true;
		} finally {
			if (id === requestId) loadingMore = false;
		}
	}

	function retry() {
		if (identity.status !== 'ready') {
			void identity.retry();
			return;
		}
		const id = ++requestId;
		loading = true;
		failed = false;
		moreError = false;
		const userId = identity.me?.id;
		if (!userId) return;
		void refresh(query, userId, id);
	}

	function openCase(id: string) {
		void goto(resolve('/cases/[caseId]', { caseId: id }));
	}
</script>

<svelte:head>
	<title>Worklist · Consilium</title>
	<meta
		name="description"
		content="Histopathology case worklist for retrieval-led precedent review."
	/>
</svelte:head>

<div class="page">
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Case review</Typography>
			<Typography as="h1" style="display">Worklist</Typography>
			<Typography tone="secondary">
				Review assigned cases, then retrieve precedent from tissue and prior reports.
			</Typography>
		</div>
		<div class="queue-summary">
			<div>
				<Typography style="title">{openCount}</Typography>
				<Typography style="small" tone="muted">Open in your queue</Typography>
			</div>
			<div>
				<Typography style="title">{queueCount}</Typography>
				<Typography style="small" tone="muted">Assigned to you</Typography>
			</div>
			<Button href="/ingest" variant="secondary" icon="ingest">Ingest slide</Button>
		</div>
	</div>

	<section
		class="surface worklist"
		aria-label="Case worklist"
		aria-busy={screen.kind === 'loading'}
		data-screen={screen.kind}
	>
		<div class="view-bar">
			<SegmentedControl
				value={query.view}
				onchange={setView}
				items={[
					{ label: 'My cases', value: 'mine', count: mineCount },
					{ label: 'All cases', value: 'all', count: allCount }
				]}
			/>
			<div class="list-summary">
				<span class="live-dot"></span>
				<Typography style="small" tone="secondary">
					{identity.me ? `Acting as ${identity.me.name}` : 'Resolving identity'}
				</Typography>
			</div>
		</div>

		<div class="toolbar filters">
			<SelectField
				value={query.status ?? ''}
				onchange={setStatus}
				label="Status"
				compact
				options={statusOptions}
			/>
			<SelectField
				value={query.specialty ?? ''}
				onchange={setSpecialty}
				label="Specialty"
				compact
				options={specialtyOptions}
			/>
			<SelectField
				value={query.assignedTo ?? ''}
				onchange={setAssigned}
				label="Assigned to"
				compact
				options={assignedOptions}
			/>
			<IcdPrefixField
				value={query.icd10 ?? ''}
				onchange={(icd10) => applyQuery({ ...query, icd10 })}
			/>
			{#if query.patientId}
				<Badge tone="accent">Patient {query.patientId}</Badge>
			{/if}
			<div class="spacer"></div>
			{#if hasWorklistFilters(query)}
				<Button variant="ghost" size="sm" icon="close" onclick={clearFilters}>Clear filters</Button>
			{/if}
		</div>

		{#if screen.kind === 'error'}
			<div class="state-wrap">
				<StateMessage
					tone="danger"
					title={screen.title}
					description={screen.description}
					action={screen.action}
					onaction={retry}
				/>
			</div>
		{:else if screen.kind === 'loading'}
			<div class="loading-table" aria-hidden="true">
				{#each [0, 1, 2, 3, 4, 5] as row (row)}
					<div class="loading-row">
						<Skeleton height="xl" width="short" />
						<div><Skeleton width="medium" /><Skeleton height="sm" /></div>
						<Skeleton width="medium" />
						<Skeleton width="short" />
					</div>
				{/each}
			</div>
		{:else if screen.kind === 'empty-filter'}
			<EmptyState
				icon="search"
				title={screen.title}
				description={screen.description}
				action={screen.action}
				onaction={clearFilters}
			/>
		{:else if screen.kind === 'empty-queue'}
			<EmptyState
				icon="search"
				title={screen.title}
				description={screen.description}
				action={screen.action}
				onaction={showAllCases}
			/>
		{:else if screen.kind === 'no-data'}
			<EmptyState
				icon="database"
				title={screen.title}
				description={screen.description}
				action={screen.action}
				onaction={() => goto(resolve('/ingest'))}
			/>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Case</th>
							<th>Patient</th>
							<th>Status</th>
							<th>Assigned pathologist</th>
							<th>Slides</th>
							<th>ICD-10</th>
							<th>Accessioned</th>
							<th aria-label="Actions"></th>
						</tr>
					</thead>
					<tbody>
						{#each rows as item (item.id)}
							<tr
								class="case-row"
								tabindex="0"
								onclick={() => openCase(item.id)}
								onkeydown={(event) => {
									if (event.key === 'Enter' || event.key === ' ') {
										event.preventDefault();
										openCase(item.id);
									}
								}}
							>
								<td>
									<div class="case-cell">
										{#if item.thumbnailUrl}
											<TissueImage
												src={item.thumbnailUrl}
												alt={`Slide thumbnail for ${item.id}`}
												size="md"
											/>
										{:else}
											<span class="thumb-fallback" aria-hidden="true"></span>
										{/if}
										<div>
											<Button
												href={item.caseHref}
												variant="ghost"
												size="sm"
												onclick={(event) => event.stopPropagation()}
											>
												{item.id}
											</Button>
											<Typography style="small" tone="secondary">{item.specialtyLabel}</Typography>
											{#if item.conclusion}
												<Typography style="small" tone="muted">{item.conclusion}</Typography>
											{/if}
										</div>
									</div>
								</td>
								<td>
									<div class="patient-cell">
										<Button
											href={item.patientHref}
											variant="ghost"
											size="sm"
											onclick={(event) => event.stopPropagation()}
										>
											{item.patientLabel}
										</Button>
										<Typography style="small" tone="secondary">{item.ageSex}</Typography>
										{#if item.priorCases}
											<Badge tone="accent">{item.patientCaseCount} cases</Badge>
										{/if}
									</div>
								</td>
								<td>
									<Badge tone={item.status === 'open' ? 'warning' : 'success'}
										>{item.statusLabel}</Badge
									>
								</td>
								<td>
									<div class="pathologist">
										<Avatar name={item.pathologistName} size="sm" />
										<div>
											<Typography style="label">{item.pathologistName}</Typography>
											{#if item.pathologistSynthetic}
												<Typography style="small" tone="muted">Synthetic</Typography>
											{/if}
										</div>
									</div>
								</td>
								<td><Typography>{item.slideCount}</Typography></td>
								<td><Typography style="mono" tone="secondary">{item.icd10 ?? '—'}</Typography></td>
								<td><Typography style="small" tone="secondary">{item.accessioned}</Typography></td>
								<td>
									<Button
										href={item.caseHref}
										variant="ghost"
										icon="chevron-right"
										iconOnly
										ariaLabel={`Open ${item.id}`}
										onclick={(event) => event.stopPropagation()}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<footer class="list-footer">
				<div class="meta-row">
					<Icon name="database" size="sm" />
					<Typography style="small" tone="secondary">
						Showing {rows.length}{nextCursor ? '+' : ''} cases
					</Typography>
				</div>
				{#if moreError}
					<Button variant="secondary" size="sm" onclick={loadMore}>Retry next page</Button>
				{:else if loadingMore}
					<Typography style="small" tone="muted">Loading the next 50…</Typography>
				{/if}
			</footer>
			{#if nextCursor}
				<div class="page-sentinel" bind:this={sentinel} aria-hidden="true"></div>
			{/if}
		{/if}
	</section>
</div>

<style>
	.queue-summary {
		display: flex;
		align-items: center;
		gap: var(--space-6);
	}
	.queue-summary > div {
		display: grid;
		gap: var(--space-1);
		padding-left: var(--space-5);
		border-left: var(--border-width) solid var(--color-border);
	}
	.worklist {
		overflow: hidden;
	}
	.view-bar,
	.list-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-4);
	}
	.view-bar {
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.list-summary {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.live-dot {
		width: var(--space-2);
		height: var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--color-success);
		box-shadow: 0 0 0 var(--space-1) var(--color-success-soft);
	}
	.filters :global(.field) {
		min-width: 10.5rem;
	}
	.table-wrap {
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		padding: var(--space-3) var(--space-4);
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
		font: var(--font-eyebrow);
		letter-spacing: var(--tracking-wide);
		text-align: left;
		text-transform: uppercase;
		border-bottom: var(--border-width) solid var(--color-border);
		white-space: nowrap;
	}
	td {
		height: var(--table-row);
		padding: var(--space-3) var(--space-4);
		border-bottom: var(--border-width) solid var(--color-border);
		vertical-align: middle;
	}
	tbody tr {
		transition: background var(--motion-fast);
		cursor: pointer;
	}
	tbody tr:hover,
	tbody tr:focus-visible {
		background: var(--color-surface-raised);
		outline: none;
	}
	.case-cell,
	.pathologist {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.case-cell > div,
	.patient-cell,
	.pathologist > div {
		display: grid;
		gap: var(--space-1);
	}
	.case-cell :global(.button),
	.patient-cell :global(.button) {
		justify-content: flex-start;
		width: fit-content;
		min-height: auto;
		padding: 0;
		color: var(--color-action);
	}
	.case-cell :global(.type.small:last-child) {
		max-width: 24rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.thumb-fallback {
		display: block;
		width: var(--thumb-md);
		height: var(--thumb-md);
		border-radius: var(--radius-sm);
		background: var(--color-image-placeholder);
		border: var(--border-width) solid var(--color-border);
	}
	.list-footer {
		background: var(--color-surface-raised);
	}
	.page-sentinel {
		height: 1px;
	}
	.loading-table {
		display: grid;
	}
	.loading-row {
		display: grid;
		grid-template-columns: 10rem 1fr 10rem 7rem;
		align-items: center;
		gap: var(--space-6);
		min-height: var(--table-row);
		padding: var(--space-4);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.loading-row > div {
		display: grid;
		gap: var(--space-2);
	}
	.state-wrap {
		padding: var(--space-6);
	}
	@media (max-width: 880px) {
		.queue-summary > div {
			display: none;
		}
		.filters :global(.field) {
			min-width: calc(50% - var(--space-2));
		}
	}
	@media (max-width: 620px) {
		.queue-summary {
			width: 100%;
		}
		.filters :global(.field) {
			width: 100%;
		}
	}
</style>
