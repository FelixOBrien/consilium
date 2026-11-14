<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		Badge,
		Button,
		CheckField,
		EmptyState,
		Skeleton,
		StateMessage,
		TextField,
		Typography
	} from '#lib';
	import { cases, patients } from '#lib/data.js';

	let filter = $state('');
	let multiOnly = $state(false);
	let screenState = $state('ready');

	const enrichedPatients = $derived(
		patients.map((patient) => {
			const patientCases = cases.filter((item) => item.patientId === patient.id);
			const openCount = patientCases.filter((item) => item.status === 'Open').length;
			const signedCount = patientCases.length - openCount;
			return {
				...patient,
				caseCount: patientCases.length,
				openCount,
				signedCount,
				latestAccessioned: patientCases[0]?.accessioned ?? '—'
			};
		})
	);

	const filtered = $derived(
		enrichedPatients.filter((patient) => {
			if (multiOnly && patient.caseCount < 2) return false;
			if (
				filter.trim() &&
				!patient.displayLabel.toLowerCase().includes(filter.trim().toLowerCase()) &&
				!patient.specialties.some((s) => s.toLowerCase().includes(filter.trim().toLowerCase()))
			) {
				return false;
			}
			return true;
		})
	);

	onMount(() => {
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
</script>

<svelte:head>
	<title>Patients · Consilium</title>
</svelte:head>

<div class="page patients-page">
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Longitudinal history</Typography>
			<Typography as="h1" style="display">Patients</Typography>
			<Typography tone="secondary">
				Inspect longitudinal pathology timelines and search within a patient's prior specimens.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	<section class="surface patients-surface">
		<div class="toolbar">
			<TextField
				bind:value={filter}
				icon="search"
				placeholder="Filter by patient ID (PT-…) or specialty…"
				compact
			/>
			<CheckField bind:checked={multiOnly}>
				<Typography as="span" style="small">Multiple cases only</Typography>
			</CheckField>
		</div>

		{#if screenState === 'error'}
			<div class="state-wrap">
				<StateMessage
					tone="danger"
					title="Patients could not be loaded"
					description="Check the API connection and try again."
					action="Retry"
				/>
			</div>
		{:else if screenState === 'loading'}
			<div class="loading-list">
				{#each [0, 1, 2, 3] as row (row)}
					<div class="loading-row">
						<Skeleton width="short" height="lg" />
						<Skeleton width="medium" />
						<Skeleton width="short" />
					</div>
				{/each}
			</div>
		{:else if filtered.length === 0}
			<EmptyState
				icon="search"
				title="No patients match this filter"
				description="Clear the search filter or include single-case patients."
				action="Reset filters"
				onaction={() => {
					filter = '';
					multiOnly = false;
				}}
			/>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Patient</th>
							<th>Demographics</th>
							<th>Specialties</th>
							<th>Cases</th>
							<th>Latest accession</th>
							<th>Linkage</th>
							<th aria-label="Actions"></th>
						</tr>
					</thead>
					<tbody>
						{#each filtered as patient (patient.id)}
							<tr>
								<td>
									<Button href={`/patients/${patient.id}`} variant="ghost" size="sm">
										{patient.displayLabel}
									</Button>
								</td>
								<td>
									<Typography style="small" tone="secondary">
										{patient.sex} · born ~{patient.birthYear}
									</Typography>
								</td>
								<td>
									<Typography style="small">{patient.specialties.join(' · ')}</Typography>
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
										{#if patient.signedCount > 0}
											<Badge tone="success">{patient.signedCount} signed out</Badge>
										{/if}
									</div>
								</td>
								<td>
									<Typography style="small" tone="secondary">
										{patient.latestAccessioned}
									</Typography>
								</td>
								<td>
									{#if patient.isSyntheticLinkage}
										<Badge tone="synthetic">Synthetic longitudinal link</Badge>
									{:else}
										<Badge tone="neutral">Single TCGA donor</Badge>
									{/if}
								</td>
								<td>
									<Button
										href={`/patients/${patient.id}`}
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
	.toolbar :global(.field) {
		min-width: 20rem;
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
	.state-wrap {
		padding: var(--space-6);
	}
</style>
