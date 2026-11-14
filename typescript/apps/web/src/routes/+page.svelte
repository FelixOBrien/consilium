<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
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
	import { cases } from '#lib/data.js';

	let view = $state('mine');
	let status = $state('Any status');
	let specialty = $state('All specialties');
	let assigned = $state('Anyone');
	let icd = $state('All ICD-10');
	let screenState = $state('ready');
	const filtered = $derived(
		cases.filter((item) => {
			if (view === 'mine' && item.pathologist !== 'Dr A. Okafor') return false;
			if (status !== 'Any status' && item.status !== status) return false;
			if (specialty !== 'All specialties' && item.specialty !== specialty) return false;
			if (assigned !== 'Anyone' && item.pathologist !== assigned) return false;
			return true;
		})
	);
	const hasFilters = $derived(
		status !== 'Any status' ||
			specialty !== 'All specialties' ||
			assigned !== 'Anyone' ||
			icd !== 'All ICD-10'
	);

	function clearFilters() {
		status = 'Any status';
		specialty = 'All specialties';
		assigned = 'Anyone';
		icd = 'All ICD-10';
	}

	onMount(() => {
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
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
				<Typography style="title">3</Typography>
				<Typography style="small" tone="muted">Open today</Typography>
			</div>
			<div>
				<Typography style="title">12</Typography>
				<Typography style="small" tone="muted">In your queue</Typography>
			</div>
			<Button href="/ingest" variant="secondary" icon="ingest">Ingest slide</Button>
		</div>
	</div>

	<section class="surface worklist" aria-label="Case worklist">
		<div class="view-bar">
			<SegmentedControl
				bind:value={view}
				items={[
					{ label: 'My cases', value: 'mine', count: 12 },
					{ label: 'All cases', value: 'all', count: 196 }
				]}
			/>
			<div class="list-summary">
				<span class="live-dot"></span>
				<Typography style="small" tone="secondary">Updated just now</Typography>
			</div>
		</div>

		<div class="toolbar filters">
			<SelectField
				bind:value={status}
				label="Status"
				compact
				options={['Any status', 'Open', 'Signed out']}
			/>
			<SelectField
				bind:value={specialty}
				label="Specialty"
				compact
				options={['All specialties', 'Dermatopathology', 'Breast', 'Thoracic', 'Gastrointestinal']}
			/>
			<SelectField
				bind:value={assigned}
				label="Assigned to"
				compact
				options={['Anyone', 'Dr A. Okafor', 'Dr M. Laurent', 'Dr E. Mensah', 'Dr S. Chen']}
			/>
			<SelectField
				bind:value={icd}
				label="ICD-10 prefix"
				compact
				options={['All ICD-10', 'C44', 'D03', 'C18', 'C50']}
			/>
			<div class="spacer"></div>
			{#if hasFilters}
				<Button variant="ghost" size="sm" icon="close" onclick={clearFilters}>Clear filters</Button>
			{/if}
			<Button variant="secondary" size="sm" icon="filter">More filters</Button>
		</div>

		{#if screenState === 'error'}
			<div class="state-wrap">
				<StateMessage
					tone="danger"
					title="The worklist could not be loaded"
					description="Your filters have been kept. Check the API connection and try again."
					action="Retry"
				/>
			</div>
		{:else if screenState === 'loading'}
			<div class="loading-table">
				{#each [0, 1, 2, 3, 4, 5] as row (row)}
					<div class="loading-row">
						<Skeleton height="xl" width="short" />
						<div><Skeleton width="medium" /><Skeleton height="sm" /></div>
						<Skeleton width="medium" />
						<Skeleton width="short" />
					</div>
				{/each}
			</div>
		{:else if screenState === 'empty' || filtered.length === 0}
			<EmptyState
				icon="search"
				title={hasFilters ? 'No cases match these filters' : 'No open cases assigned to you'}
				description={hasFilters
					? 'Try a broader specialty or status, or clear all filters.'
					: 'Switch to All cases to browse the corpus.'}
				action={hasFilters ? 'Clear filters' : 'View all cases'}
				onaction={hasFilters ? clearFilters : () => (view = 'all')}
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
							<th>Accessed</th>
							<th aria-label="Actions"></th>
						</tr>
					</thead>
					<tbody>
						{#each filtered as item (item.id)}
							<tr>
								<td>
									<div class="case-cell">
										<TissueImage
											src={item.image}
											alt={`Slide thumbnail for ${item.id}`}
											size="md"
										/>
										<div>
											<Button href={`/cases/${item.id}?panel=report`} variant="ghost" size="sm">
												{item.id}
											</Button>
											<Typography style="small" tone="secondary">{item.specialty}</Typography>
											{#if item.status === 'Signed out'}
												<Typography style="small" tone="muted">{item.conclusion}</Typography>
											{/if}
										</div>
									</div>
								</td>
								<td>
									<div class="patient-cell">
										<Button href={`/patients/${item.patientId}`} variant="ghost" size="sm">
											{item.patientLabel}
										</Button>
										<Typography style="small" tone="secondary">{item.ageSex}</Typography>
										{#if item.patientCaseCount > 1}
											<Badge tone="accent">{item.patientCaseCount} cases</Badge>
										{/if}
									</div>
								</td>
								<td>
									<Badge tone={item.status === 'Open' ? 'warning' : 'success'}>{item.status}</Badge>
								</td>
								<td>
									<div class="pathologist">
										<Avatar name={item.pathologist} size="sm" />
										<div>
											<Typography style="label">{item.pathologist}</Typography>
											<Typography style="small" tone="muted">Synthetic</Typography>
										</div>
									</div>
								</td>
								<td><Typography>{item.slides}</Typography></td>
								<td><Typography style="mono" tone="secondary">{item.icd10}</Typography></td>
								<td><Typography style="small" tone="secondary">{item.accessioned}</Typography></td>
								<td>
									<Button
										href={`/cases/${item.id}?panel=report`}
										variant="ghost"
										icon="chevron-right"
										iconOnly
										ariaLabel={`Open ${item.id}`}
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
						Showing {filtered.length} of {view === 'mine' ? '12' : '196'} cases
					</Typography>
				</div>
				<Button variant="secondary" size="sm">Load next 50</Button>
			</footer>
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
	}
	tbody tr:hover {
		background: var(--color-surface-raised);
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
	.list-footer {
		background: var(--color-surface-raised);
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
