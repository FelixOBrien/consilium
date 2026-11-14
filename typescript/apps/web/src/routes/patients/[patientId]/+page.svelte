<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		Avatar,
		Badge,
		Button,
		Dialog,
		EmptyState,
		Icon,
		SegmentedControl,
		Skeleton,
		StateMessage,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { cases, evidenceResults, patients, tissueImages } from '#lib/data.js';

	let query = $state('');
	let mode = $state('reports');
	let screenState = $state('ready');
	let peekOpen = $state(false);
	let peekCase = $state(cases[4]);

	const patientId = $derived(page.params.patientId);
	const patient = $derived(patients.find((item) => item.id === patientId));
	const patientCases = $derived(cases.filter((item) => item.patientId === patientId));
	const signedOutCases = $derived(patientCases.filter((item) => item.status === 'Signed out'));
	const openCasesCount = $derived(patientCases.length - signedOutCases.length);
	const matchingCases = $derived(
		query.trim()
			? signedOutCases.filter(
					(item) =>
						item.conclusion.toLowerCase().includes(query.trim().toLowerCase()) ||
						item.specimenLabel.toLowerCase().includes(query.trim().toLowerCase()) ||
						item.specialty.toLowerCase().includes(query.trim().toLowerCase()) ||
						item.icd10.toLowerCase().includes(query.trim().toLowerCase())
				)
			: []
	);

	function openPeek(item: (typeof cases)[number]) {
		peekCase = item;
		peekOpen = true;
	}

	function passageFor(caseId: string) {
		return (
			evidenceResults.find((hit) => hit.id === caseId)?.passage ??
			'Sectioned surgical specimen reviewed; see full report body in workspace.'
		);
	}

	onMount(() => {
		query = page.url.searchParams.get('q') ?? '';
		mode = page.url.searchParams.get('mode') ?? 'reports';
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
</script>

<svelte:head>
	<title>{patient?.displayLabel ?? patientId} · Patient · Consilium</title>
</svelte:head>

<div class="page patient-page">
	{#if screenState === 'loading'}
		<section class="surface loading-wrap">
			<Skeleton width="short" height="lg" />
			<Skeleton width="medium" />
			<Skeleton height="xl" />
		</section>
	{:else if screenState === 'error'}
		<StateMessage
			tone="danger"
			title="Patient record could not be loaded"
			description="Check the API connection and try again."
			action="Retry"
		/>
	{:else if !patient}
		<section class="surface">
			<EmptyState
				icon="warning"
				title="Patient not found"
				description="No patient with this identifier exists in the loaded cohort."
				action="Browse all patients"
				onaction={() => (window.location.href = '/patients')}
			/>
		</section>
	{:else}
		<div class="page-heading">
			<div class="heading-copy">
				<Typography as="span" style="eyebrow" tone="accent">S-09 · Patient record</Typography>
				<div class="title-row">
					<Typography as="h1" style="display">{patient.displayLabel}</Typography>
					{#if patient.isSyntheticLinkage}
						<Badge tone="synthetic">Synthetic longitudinal linkage</Badge>
					{/if}
				</div>
				<Typography tone="secondary">
					Sex {patient.sex} · Approx. birth year {patient.birthYear} · Specialties:
					{patient.specialties.join(', ')}
				</Typography>
			</div>
			<div class="header-actions">
				<Button href="/patients" variant="secondary" icon="arrow-left">All patients</Button>
				<Button href="/" variant="ghost">Worklist</Button>
			</div>
		</div>

		<div class="summary-grid">
			<div class="surface stat">
				<Typography style="title">{patientCases.length}</Typography>
				<Typography style="small" tone="muted">Total cases</Typography>
			</div>
			<div class="surface stat">
				<Typography style="title">{openCasesCount}</Typography>
				<Typography style="small" tone="muted">Open (unreported)</Typography>
			</div>
			<div class="surface stat">
				<Typography style="title">{signedOutCases.length}</Typography>
				<Typography style="small" tone="muted">Signed-out prior cases</Typography>
			</div>
		</div>

		<section class="surface patient-search">
			<div class="search-head">
				<div>
					<Typography as="h2" style="section">Search this patient's cases</Typography>
					<Typography style="small" tone="secondary">
						Scoped to signed-out cases of {patient.displayLabel} (open unreported cases are excluded).
					</Typography>
				</div>
				<SegmentedControl
					bind:value={mode}
					items={[
						{ label: 'Reports', value: 'reports' },
						{ label: 'Tissue', value: 'tissue' }
					]}
				/>
			</div>
			<div class="search-bar">
				<TextField
					bind:value={query}
					icon={mode === 'reports' ? 'report' : 'evidence'}
					placeholder={mode === 'reports'
						? `Search ${patient.displayLabel} prior report text or ICD-10…`
						: `Describe tissue morphology across ${patient.displayLabel}'s slides…`}
				/>
				{#if query.trim()}
					<Button variant="ghost" icon="close" onclick={() => (query = '')}>Clear</Button>
				{/if}
			</div>
		</section>

		{#if query.trim()}
			<section class="surface results-surface">
				<header class="timeline-header">
					<div>
						<Typography as="h2" style="section">
							Patient search results ({matchingCases.length})
						</Typography>
						<Typography style="small" tone="muted">
							Mode: {mode === 'reports' ? 'Reports' : 'Tissue patches'} · Patient {patient.displayLabel}
						</Typography>
					</div>
				</header>

				{#if matchingCases.length === 0}
					<EmptyState
						icon="search"
						title="No signed-out cases for this patient matched"
						description="Clear the query to see the full timeline, or run the query across the whole corpus."
						action="Clear patient query"
						onaction={() => (query = '')}
					/>
				{:else}
					<div class="timeline-list">
						{#each matchingCases as item (item.id)}
							<article class="case-card">
								<TissueImage src={item.image} alt={`Slide thumbnail for ${item.id}`} size="lg" />
								<div class="case-body">
									<div class="case-top">
										<div>
											<Typography as="h3" style="subsection">{item.id}</Typography>
											<Typography style="small" tone="secondary">
												{item.specimenLabel} · {item.specialty} · {item.ageSex} · {item.accessioned}
											</Typography>
										</div>
										<div class="badges">
											<Badge tone="success">Signed out</Badge>
											<Badge tone="neutral">{item.icd10}</Badge>
										</div>
									</div>

									{#if mode === 'reports'}
										<div class="passage">
											<Typography style="eyebrow" tone="muted">Matched report excerpt</Typography>
											<Typography>{item.conclusion} {passageFor(item.id)}</Typography>
										</div>
									{:else}
										<div class="patch-strip">
											{#each [item.image, tissueImages.epithelium] as patchImg, idx (idx)}
												<TissueImage
													src={patchImg}
													alt={`Matched patch ${idx + 1} for ${item.id}`}
													size="md"
												/>
											{/each}
											<Typography style="small" tone="secondary">{item.conclusion}</Typography>
										</div>
									{/if}

									<div class="case-footer">
										<div class="author">
											<Avatar name={item.pathologist} size="sm" />
											<Typography style="small">{item.pathologist}</Typography>
											<Badge tone="synthetic">Synthetic</Badge>
										</div>
										<div class="actions">
											<Button variant="secondary" size="sm" onclick={() => openPeek(item)}>
												Peek
											</Button>
											<Button
												href={`/cases/${item.id}?panel=${mode === 'reports' ? 'report' : 'evidence'}`}
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
		{:else}
			<section class="surface timeline-surface">
				<header class="timeline-header">
					<div>
						<Typography as="h2" style="section">Chronological case timeline</Typography>
						<Typography style="small" tone="muted">
							{patientCases.length === 1
								? 'Single-specimen record — no prior cases recorded for this patient.'
								: `${patientCases.length} cases ordered newest first`}
						</Typography>
					</div>
				</header>

				<div class="timeline-list">
					{#each patientCases as item (item.id)}
						<article class="case-card">
							<TissueImage src={item.image} alt={`Slide thumbnail for ${item.id}`} size="lg" />
							<div class="case-body">
								<div class="case-top">
									<div>
										<Typography as="h3" style="subsection">{item.id}</Typography>
										<Typography style="small" tone="secondary">
											{item.specimenLabel} · {item.specialty} · {item.ageSex} · {item.slides}
											{item.slides === 1 ? 'slide' : 'slides'} · {item.accessioned}
										</Typography>
									</div>
									<div class="badges">
										<Badge tone={item.status === 'Open' ? 'warning' : 'success'}>
											{item.status}
										</Badge>
										{#if item.status === 'Signed out'}
											<Badge tone="neutral">{item.icd10}</Badge>
										{/if}
									</div>
								</div>

								{#if item.status === 'Signed out'}
									<Typography>{item.conclusion}</Typography>
								{:else}
									<div class="open-notice">
										<Icon name="warning" size="sm" />
										<Typography style="small" tone="secondary">
											Open case — report and diagnosis codes withheld until sign-out. Open in
											workspace to consult the agent across prior history.
										</Typography>
									</div>
								{/if}

								<div class="case-footer">
									<div class="author">
										<Avatar name={item.pathologist} size="sm" />
										<Typography style="small">
											{item.status === 'Open' ? 'Assigned to' : 'Reported by'}
											{item.pathologist}
										</Typography>
										<Badge tone="synthetic">Synthetic</Badge>
									</div>
									<div class="actions">
										<Button variant="secondary" size="sm" onclick={() => openPeek(item)}>
											Peek
										</Button>
										{#if item.status === 'Open' && signedOutCases.length > 0}
											<Button
												href={`/cases/${item.id}?panel=consult`}
												variant="secondary"
												size="sm"
												icon="spark"
											>
												Consult with history
											</Button>
										{/if}
										<Button
											href={`/cases/${item.id}?panel=report`}
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
			</section>
		{/if}
	{/if}
</div>

<Dialog open={peekOpen} title={`Case peek · ${peekCase.id}`} onclose={() => (peekOpen = false)}>
	<div class="peek">
		<div class="peek-slide">
			<TissueImage src={peekCase.image} alt={`Slide for ${peekCase.id}`} size="viewer" />
		</div>
		<div class="peek-report">
			<div>
				<Typography style="eyebrow" tone="accent">
					{peekCase.status === 'Signed out' ? 'Signed report' : 'Open case'}
				</Typography>
				<Typography as="h3" style="section">{peekCase.id}</Typography>
				<Typography style="small" tone="secondary">
					{peekCase.specimenLabel} · {peekCase.pathologist}
				</Typography>
			</div>
			{#if peekCase.status === 'Signed out'}
				<div class="peek-section">
					<Typography style="eyebrow" tone="muted">Conclusion</Typography>
					<Typography>{peekCase.conclusion}</Typography>
				</div>
				<div class="peek-section">
					<Typography style="eyebrow" tone="muted">Report excerpt</Typography>
					<Typography>{passageFor(peekCase.id)}</Typography>
				</div>
			{:else}
				<StateMessage
					tone="warning"
					title="Not yet reported"
					description="Only submitted clinical history is visible before sign-out."
				/>
			{/if}
			<Button href={`/cases/${peekCase.id}?panel=report`} variant="primary" icon="external">
				Open full case
			</Button>
		</div>
	</div>
</Dialog>

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
	.patch-strip {
		display: flex;
		align-items: center;
		gap: var(--space-2);
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
		grid-template-columns: 1fr auto;
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
	.open-notice {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-warning-soft);
	}
	.loading-wrap {
		display: grid;
		gap: var(--space-4);
		padding: var(--space-6);
	}
	.peek {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(20rem, 0.85fr);
		min-height: 28rem;
	}
	.peek-slide {
		background: var(--color-viewer);
	}
	.peek-report {
		display: grid;
		align-content: start;
		gap: var(--space-5);
		padding: var(--space-6);
	}
	.peek-section {
		display: grid;
		gap: var(--space-1);
	}
	@media (max-width: 760px) {
		.summary-grid,
		.case-card,
		.peek {
			grid-template-columns: 1fr;
		}
		.search-head,
		.case-top,
		.case-footer {
			flex-direction: column;
		}
	}
</style>
