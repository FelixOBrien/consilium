<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		Avatar,
		Badge,
		Button,
		EmptyState,
		Icon,
		Pressable,
		SelectField,
		Skeleton,
		StateMessage,
		TextField,
		Typography
	} from '#lib';
	import { jobs } from '#lib/data.js';

	let dataset = $state('histai/HISTAI-skin-b1');
	let slidePath = $state('case_014218/slide_HE_1.tiff');
	let selectedIndex = $state(0);
	let screenState = $state('ready');
	const selectedJob = $derived(jobs[selectedIndex]);
	const stages = [
		'Download slide',
		'Segment tissue',
		'Embed patches',
		'Project features',
		'Build thumbnails',
		'Process report',
		'Load database',
		'Build indexes'
	];

	onMount(() => {
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
</script>

<svelte:head>
	<title>Ingestion · Consilium</title>
</svelte:head>

<div class="page ingest-page">
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Data operations</Typography>
			<Typography as="h1" style="display">Ingestion pipeline</Typography>
			<Typography tone="secondary">
				Queue a HistAI slide and watch it become searchable precedent.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	<div class="corpus-grid">
		{#each [['196', 'Cases'], ['243', 'Slides'], ['824k', 'Patches'], ['3,482', 'Report chunks']] as stat (stat[1])}
			<div class="surface stat">
				<Typography style="title">{stat[0]}</Typography>
				<Typography style="small" tone="muted">{stat[1]} loaded</Typography>
			</div>
		{/each}
		<div class="surface corpus-health">
			<span class="health-mark"><Icon name="activity" /></span>
			<div>
				<Typography style="label">Corpus healthy</Typography>
				<Typography style="small" tone="muted">Postgres + pgvector · checked 1 min ago</Typography>
			</div>
		</div>
	</div>

	<section class="surface new-job">
		<div>
			<Typography style="eyebrow" tone="accent">New single-slide job</Typography>
			<Typography as="h2" style="section">Queue from HistAI</Typography>
			<Typography style="small" tone="secondary">
				Reference a known dataset path. Files are downloaded by the GPU worker.
			</Typography>
		</div>
		<SelectField
			bind:value={dataset}
			label="Dataset"
			options={[
				'histai/HISTAI-skin-b1',
				'histai/HISTAI-breast',
				'histai/HISTAI-thorax',
				'histai/HISTAI-colorectal-b1'
			]}
		/>
		<TextField bind:value={slidePath} label="Slide path" icon="database" />
		<Button variant="primary" icon="ingest">Queue ingestion</Button>
	</section>

	{#if screenState === 'error'}
		<StateMessage
			tone="danger"
			title="Ingestion jobs could not be loaded"
			description="The form is still available. Check the API connection before submitting."
			action="Retry"
		/>
	{:else if screenState === 'empty'}
		<section class="surface">
			<EmptyState
				icon="database"
				title="No ingestion jobs yet"
				description="Choose a HistAI dataset and a slide path to queue the first job."
			/>
		</section>
	{:else if screenState === 'loading'}
		<div class="pipeline-layout">
			<section class="surface job-list">
				{#each [0, 1, 2] as row (row)}
					<div class="job-row"><Skeleton height="lg" /><Skeleton /></div>
				{/each}
			</section>
			<section class="surface detail-loading">
				<Skeleton height="lg" width="medium" />
				{#each [0, 1, 2, 3, 4, 5] as row (row)}<Skeleton />{/each}
			</section>
		</div>
	{:else}
		<div class="pipeline-layout">
			<section class="surface job-list">
				<header>
					<div>
						<Typography as="h2" style="section">Recent jobs</Typography>
						<Typography style="small" tone="muted">Polling while work is active</Typography>
					</div>
					<Badge tone="info">1 running</Badge>
				</header>
				{#each jobs as job, index (job.path)}
					<Pressable
						className="job-row"
						selected={selectedIndex === index}
						onclick={() => (selectedIndex = index)}
					>
						<div class="job-row-top">
							<Badge
								tone={job.status === 'Done'
									? 'success'
									: job.status === 'Failed'
										? 'danger'
										: 'info'}>{job.status}</Badge
							>
							<Typography style="small" tone="muted">{job.time}</Typography>
						</div>
						<Typography style="label">{job.dataset.replace('HISTAI-', '')}</Typography>
						<Typography style="mono" tone="secondary">{job.path}</Typography>
						<div class="meta-row">
							<Avatar name="Dr A. Okafor" size="sm" />
							<Typography style="small" tone="muted">{job.stage}</Typography>
						</div>
					</Pressable>
				{/each}
			</section>

			<section class="surface job-detail">
				<header>
					<div>
						<Typography style="eyebrow" tone="accent">Selected job</Typography>
						<Typography as="h2" style="section">{selectedJob.path}</Typography>
						<Typography style="small" tone="muted">{selectedJob.dataset}</Typography>
					</div>
					<div class="detail-actions">
						<Badge
							tone={selectedJob.status === 'Done'
								? 'success'
								: selectedJob.status === 'Failed'
									? 'danger'
									: 'info'}>{selectedJob.status}</Badge
						>
						{#if selectedJob.status === 'Done'}
							<Button href="/cases/breast-008412?panel=report" size="sm" variant="primary">
								Open case
							</Button>
						{:else if selectedJob.status === 'Failed'}
							<Button size="sm" variant="secondary">Retry job</Button>
						{/if}
					</div>
				</header>

				{#if selectedJob.status === 'Failed'}
					<StateMessage
						tone="danger"
						title="Tissue segmentation failed"
						description="Slide resolution metadata was unavailable. Supply 0.5 μm/px and retry."
					/>
				{:else if selectedJob.status === 'Running'}
					<StateMessage
						tone="info"
						title="GPU worker active"
						description="Current stage: projecting 768-dimensional CONCH-Z features."
					/>
				{/if}

				<div class="timeline">
					{#each stages as stage, index (stage)}
						<div
							class="stage"
							class:done={selectedJob.status === 'Done' || index < 3}
							class:active={selectedJob.status === 'Running' && index === 3}
							class:failed={selectedJob.status === 'Failed' && index === 1}
						>
							<span class="stage-marker">{index + 1}</span>
							<div>
								<Typography style="label">{stage}</Typography>
								<Typography style="small" tone="muted">
									{selectedJob.status === 'Done'
										? `${(index + 1) * 6}s · complete`
										: index < 3
											? `${(index + 1) * 9}s · complete`
											: index === 3 && selectedJob.status === 'Running'
												? '12,840 / 18,290 patches'
												: index === 1 && selectedJob.status === 'Failed'
													? 'Stopped after 4s'
													: 'Waiting'}
								</Typography>
							</div>
							{#if selectedJob.status === 'Running' && index === 3}
								<div class="progress"><span></span></div>
							{/if}
						</div>
					{/each}
				</div>

				<div class="counts">
					<div>
						<Typography style="title">18,290</Typography>
						<Typography style="small" tone="muted">Patches</Typography>
					</div>
					<div>
						<Typography style="title">14</Typography>
						<Typography style="small" tone="muted">Report chunks</Typography>
					</div>
					<div>
						<Typography style="title">1</Typography>
						<Typography style="small" tone="muted">Slide</Typography>
					</div>
				</div>
			</section>
		</div>
	{/if}
</div>

<style>
	.ingest-page {
		max-width: 82rem;
	}
	.corpus-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr) 2fr;
		gap: var(--space-3);
		margin-bottom: var(--space-5);
	}
	.stat,
	.corpus-health {
		padding: var(--space-4);
	}
	.stat {
		display: grid;
		gap: var(--space-1);
	}
	.corpus-health {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.corpus-health > div {
		display: grid;
		gap: var(--space-1);
	}
	.health-mark {
		display: grid;
		place-items: center;
		width: var(--control-lg);
		height: var(--control-lg);
		border-radius: var(--radius-pill);
		background: var(--color-success-soft);
		color: var(--color-success);
	}
	.new-job {
		display: grid;
		grid-template-columns: 1.25fr 1fr 1.5fr auto;
		align-items: end;
		gap: var(--space-4);
		padding: var(--space-5);
		margin-bottom: var(--space-5);
	}
	.new-job > div:first-child {
		display: grid;
		gap: var(--space-1);
	}
	.pipeline-layout {
		display: grid;
		grid-template-columns: minmax(18rem, 0.75fr) minmax(30rem, 1.4fr);
		gap: var(--space-5);
		align-items: start;
	}
	.job-list,
	.job-detail {
		overflow: hidden;
	}
	.job-list > header,
	.job-detail > header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-5);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.job-list > header > div,
	.job-detail > header > div:first-child {
		display: grid;
		gap: var(--space-1);
	}
	.job-list :global(button.job-row) {
		display: grid;
		width: 100%;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-5);
		border: 0;
		border-bottom: var(--border-width) solid var(--color-border);
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.job-list :global(button.job-row:hover),
	.job-list :global(button.job-row.selected) {
		background: var(--color-surface-raised);
	}
	.job-list :global(button.job-row.selected) {
		box-shadow: inset 0.1875rem 0 var(--color-action);
	}
	.job-row-top,
	.detail-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}
	.job-detail {
		padding-bottom: var(--space-5);
	}
	.job-detail > :global(.state-message) {
		margin: var(--space-5) var(--space-5) 0;
	}
	.timeline {
		display: grid;
		padding: var(--space-6);
	}
	.stage {
		position: relative;
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-3);
		min-height: 4rem;
		padding-bottom: var(--space-4);
	}
	.stage::before {
		content: '';
		position: absolute;
		top: var(--control-sm);
		bottom: 0;
		left: calc(var(--control-sm) / 2);
		width: var(--border-width);
		background: var(--color-border);
	}
	.stage:last-child::before {
		display: none;
	}
	.stage-marker {
		position: relative;
		z-index: 1;
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
		color: var(--color-text-muted);
		font: var(--font-label-xs);
		border: var(--border-width) solid var(--color-border);
	}
	.stage > div {
		display: grid;
		gap: var(--space-1);
	}
	.stage.done .stage-marker {
		background: var(--color-success);
		color: var(--color-text-inverse);
		border-color: var(--color-success);
	}
	.stage.active .stage-marker {
		background: var(--color-action);
		color: var(--color-text-inverse);
		border-color: var(--color-action);
		box-shadow: 0 0 0 var(--space-1) var(--color-action-soft);
	}
	.stage.failed .stage-marker {
		background: var(--color-danger);
		color: var(--color-text-inverse);
		border-color: var(--color-danger);
	}
	.progress {
		position: absolute;
		right: 0;
		bottom: var(--space-5);
		width: 8rem;
		height: var(--space-1);
		overflow: hidden;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
	}
	.progress span {
		display: block;
		width: 70%;
		height: 100%;
		background: var(--color-action);
	}
	.counts {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		margin: 0 var(--space-5);
		padding: var(--space-4);
		border-radius: var(--radius-md);
		background: var(--color-surface-subtle);
	}
	.counts > div {
		display: grid;
		gap: var(--space-1);
		text-align: center;
		border-right: var(--border-width) solid var(--color-border);
	}
	.counts > div:last-child {
		border-right: 0;
	}
	.detail-loading {
		display: grid;
		gap: var(--space-5);
		padding: var(--space-6);
	}
	@media (max-width: 1000px) {
		.corpus-grid {
			grid-template-columns: repeat(4, 1fr);
		}
		.corpus-health {
			grid-column: 1 / -1;
		}
		.new-job {
			grid-template-columns: 1fr 1fr;
		}
	}
	@media (max-width: 760px) {
		.corpus-grid {
			grid-template-columns: repeat(2, 1fr);
		}
		.new-job,
		.pipeline-layout {
			grid-template-columns: 1fr;
		}
	}
</style>
