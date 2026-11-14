<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Badge, Button, EmptyState, Skeleton, StateMessage, TextField, Typography } from '#lib';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	import { appendPatients, fetchPatientPage, type PatientPage } from '#lib/patients/load.js';
	import { presentDirectoryRow, SYNTHETIC_LINKAGE } from '#lib/patients/present.js';
	import {
		directoryKey,
		parseDirectoryQuery,
		writeDirectoryQuery,
		type DirectoryQuery
	} from '#lib/patients/query.js';
	import { directoryScreen } from '#lib/patients/screen.js';
	import type { PatientSummary } from '#lib/patients/types.js';

	const productName = 'Consilium'; // pragma: allowlist secret

	let items = $state<PatientSummary[]>([]);
	let nextCursor = $state<string | null>(null);
	let loading = $state(true);
	let failed = $state(false);
	let loadingMore = $state(false);
	let moreError = $state(false);
	let filter = $state('');
	let reloadNonce = $state(0);
	let requestId = 0;
	let appliedKey = '';
	let filterTimer: ReturnType<typeof setTimeout> | undefined;

	const directory = $derived(parseDirectoryQuery(page.url.searchParams));
	const rows = $derived(items.map(presentDirectoryRow));
	const screen = $derived(
		directoryScreen({
			loading,
			failed,
			itemCount: items.length,
			query: directory
		})
	);

	$effect(() => {
		const key = directoryKey(directory);
		if (key === appliedKey) return;
		appliedKey = key;
		filter = directory.q;
	});

	$effect(() => {
		const current = directory;
		void reloadNonce;
		const token = ++requestId;
		loading = true;
		failed = false;
		moreError = false;
		items = [];
		nextCursor = null;
		void refresh(current, token);
	});

	$effect(() => {
		return () => clearTimeout(filterTimer);
	});

	function commit(next: DirectoryQuery) {
		clearTimeout(filterTimer);
		const normalised: DirectoryQuery = { q: next.q.trim(), multiCase: next.multiCase };
		appliedKey = directoryKey(normalised);
		const url = writeDirectoryQuery(new URL(page.url.href), normalised);
		const target = `${url.pathname}${url.search}`;
		const current = `${page.url.pathname}${page.url.search}`;
		if (target === current) return;
		void goto(resolve(target as '/'), { replace: true, reset: false });
	}

	function scheduleFilter() {
		clearTimeout(filterTimer);
		filterTimer = setTimeout(() => {
			commit({ q: filter, multiCase: directory.multiCase });
		}, 250);
	}

	function submitFilter(event: SubmitEvent) {
		event.preventDefault();
		commit({ q: filter, multiCase: directory.multiCase });
	}

	function setMultiCase(value: boolean | 'indeterminate') {
		commit({ q: filter, multiCase: value === true });
	}

	function resetFilters() {
		filter = '';
		commit({ q: '', multiCase: false });
	}

	async function refresh(current: DirectoryQuery, token: number) {
		try {
			const first: PatientPage = await fetchPatientPage(current, null);
			if (token !== requestId) return;
			items = first.items;
			nextCursor = first.nextCursor;
			loading = false;
		} catch {
			if (token !== requestId) return;
			items = [];
			nextCursor = null;
			loading = false;
			failed = true;
		}
	}

	async function loadMore() {
		if (!nextCursor || loadingMore || loading || failed) return;
		const cursor = nextCursor;
		const current = directory;
		const token = requestId;
		loadingMore = true;
		moreError = false;
		try {
			const next = await fetchPatientPage(current, cursor);
			if (token !== requestId) return;
			items = appendPatients(items, next.items);
			nextCursor = next.nextCursor;
		} catch {
			if (token !== requestId) return;
			moreError = true;
		} finally {
			if (token === requestId) loadingMore = false;
		}
	}

	function retry() {
		reloadNonce += 1;
	}
</script>

<svelte:head>
	<title>Patients · {productName}</title>
</svelte:head>

<div class="page patients-page">
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Longitudinal history</Typography>
			<Typography as="h1" style="display">Patients</Typography>
			<Typography tone="secondary">
				Inspect a patient's cases over time. Open cases stay unreported until sign-out.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	<section class="surface patients-surface">
		<div class="toolbar">
			<form class="filter-form" onsubmit={submitFilter} oninput={scheduleFilter}>
				<TextField
					bind:value={filter}
					icon="search"
					placeholder="Search by patient ID (PT-…) or label…"
					compact
					name="q"
					type="search"
				/>
				<Button type="submit" variant="secondary" size="sm">Search</Button>
			</form>
			<label class="multi-case">
				<Checkbox checked={directory.multiCase} onCheckedChange={setMultiCase} />
				<Typography as="span" style="small">Multiple cases only</Typography>
			</label>
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
			<div class="loading-list" aria-busy="true">
				{#each [0, 1, 2, 3] as row (row)}
					<div class="loading-row">
						<Skeleton width="short" height="lg" />
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
				onaction={resetFilters}
			/>
		{:else if screen.kind === 'empty'}
			<EmptyState
				icon="database"
				title={screen.title}
				description={screen.description}
				action={screen.action}
				onaction={() => goto(resolve('/'))}
			/>
		{:else}
			<div class="table-wrap">
				<table>
					<caption class="caption">
						{rows.length}
						{rows.length === 1 ? 'patient' : 'patients'}
						{#if nextCursor}
							· more available
						{/if}
					</caption>
					<thead>
						<tr>
							<th>Patient</th>
							<th>Sex</th>
							<th>Specialties</th>
							<th>Cases</th>
							<th>Latest accession</th>
							<th>Linkage</th>
							<th aria-label="Actions"></th>
						</tr>
					</thead>
					<tbody>
						{#each rows as patient (patient.id)}
							<tr>
								<td>
									<Button href={patient.href} variant="ghost" size="sm">
										{patient.displayLabel}
									</Button>
								</td>
								<td>
									<Typography style="small" tone="secondary">{patient.sexSummary}</Typography>
								</td>
								<td>
									<Typography style="small">{patient.specialties}</Typography>
								</td>
								<td>
									<div class="case-badges">
										<Badge tone={patient.caseCount > 1 ? 'accent' : 'neutral'}>
											{patient.caseCount}
											{patient.caseCount === 1 ? 'case' : 'cases'}
										</Badge>
										{#if patient.openCount > 0}
											<Badge tone="warning">{patient.openCount} open</Badge>
										{/if}
										{#if patient.signedOutCount > 0}
											<Badge tone="success">{patient.signedOutCount} signed out</Badge>
										{/if}
									</div>
								</td>
								<td>
									<Typography style="small" tone="secondary">
										{patient.latestAccessioned}
									</Typography>
								</td>
								<td>
									{#if patient.syntheticLinkage}
										<Badge tone="synthetic">{SYNTHETIC_LINKAGE}</Badge>
									{/if}
								</td>
								<td>
									<Button
										href={patient.href}
										variant="ghost"
										icon="chevron-right"
										iconOnly
										ariaLabel={`Open ${patient.displayLabel}`}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if moreError}
				<div class="state-wrap">
					<StateMessage
						tone="danger"
						title="More patients could not be loaded"
						description="The patients already listed are unchanged."
						action="Try again"
						onaction={() => void loadMore()}
					/>
				</div>
			{/if}
			{#if nextCursor}
				<div class="more">
					<Button variant="secondary" disabled={loadingMore} onclick={() => void loadMore()}>
						{loadingMore ? 'Loading…' : 'Load more'}
					</Button>
				</div>
			{/if}
		{/if}
	</section>
</div>

<style>
	.patients-page {
		max-width: 82rem;
	}
	.patients-surface {
		overflow: hidden;
	}
	.filter-form {
		display: flex;
		flex: 1;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-3);
		min-width: min(100%, 18rem);
	}
	.filter-form :global(.field) {
		min-width: min(100%, 16rem);
		flex: 1;
	}
	.multi-case {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-md);
		cursor: pointer;
	}
	.caption {
		padding: var(--space-3) var(--space-4) 0;
		caption-side: top;
		text-align: left;
		color: var(--color-text-muted);
		font: var(--font-label-sm);
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
	td :global(.button) {
		padding: 0;
		min-height: auto;
		color: var(--color-action);
	}
	.case-badges {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.loading-list {
		display: grid;
	}
	.loading-row {
		display: grid;
		grid-template-columns: 8rem 1fr 8rem;
		gap: var(--space-4);
		padding: var(--space-4);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.state-wrap,
	.more {
		padding: var(--space-4);
	}
</style>
