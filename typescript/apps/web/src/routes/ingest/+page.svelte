<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
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
	import { formatCount, formatDuration, formatTimestamp } from '#lib/ingest/format.js';
	import { createJob, fetchHealth, getJob, listJobs } from '#lib/ingest/load.js';
	import {
		corpusFromHealth,
		interpretSubmit,
		queuedWithoutWorker,
		replaceJob,
		statusTone,
		transitionedToDone,
		upsertJob,
		type CorpusSnapshot,
		type SubmitNotice
	} from '#lib/ingest/outcomes.js';
	import {
		createPollScheduler,
		hasActiveJob,
		isActiveStatus,
		POLL_INTERVAL_MS
	} from '#lib/ingest/polling.js';
	import {
		COHORT_PROJECTS,
		EMPTY_JOBS_DESCRIPTION,
		EMPTY_JOBS_TITLE,
		NO_WORKER_DESCRIPTION,
		NO_WORKER_TITLE
	} from '#lib/ingest/projects.js';
	import { deriveTimeline, stageLabel } from '#lib/ingest/timeline.js';
	import type { IngestionJob } from '#lib/ingest/types.js';

	let dataset = $state<(typeof COHORT_PROJECTS)[number]>(COHORT_PROJECTS[0]);
	let slidePath = $state('');
	let jobs = $state<IngestionJob[]>([]);
	let selectedId = $state<string | null>(null);
	let listPhase = $state<'loading' | 'ready' | 'error'>('loading');
	let listError = $state<string | null>(null);
	let detailError = $state<string | null>(null);
	let corpus = $state<CorpusSnapshot>({ kind: 'loading' });
	let submitting = $state(false);
	let formError = $state<string | null>(null);
	let notice = $state<SubmitNotice | null>(null);
	let retriedAt = $state<Record<string, number>>({});
	let now = $state(Date.now());
	let polling = $state(false);

	let disposed = false;
	let epoch = 0;
	let pollInFlight = false;
	let submitGeneration = 0;

	const active = $derived(hasActiveJob(jobs));
	const selected = $derived(jobs.find((job) => job.id === selectedId) ?? null);
	const timeline = $derived(selected ? deriveTimeline(selected) : []);
	const noWorker = $derived(queuedWithoutWorker(jobs, now, retriedAt));
	const failedItem = $derived(timeline.find((item) => item.state === 'failed') ?? null);
	const corpusStats = $derived(
		corpus.kind === 'ready'
			? [
					{ label: 'Cases', value: formatCount(corpus.cases) },
					{ label: 'Slides', value: formatCount(corpus.slides) },
					{ label: 'Patches', value: formatCount(corpus.patches) },
					{ label: 'Report chunks', value: formatCount(corpus.reportChunks) }
				]
			: [
					{ label: 'Cases', value: '—' },
					{ label: 'Slides', value: '—' },
					{ label: 'Patches', value: '—' },
					{ label: 'Report chunks', value: '—' }
				]
	);

	const scheduler = createPollScheduler({
		intervalMs: POLL_INTERVAL_MS,
		onTick: () => {
			void poll();
		}
	});

	function errorText(error: unknown, fallback: string): string {
		return error instanceof Error && error.message ? error.message : fallback;
	}

	async function refreshCorpus() {
		try {
			const health = await fetchHealth();
			if (disposed) return;
			corpus = corpusFromHealth(health);
		} catch {
			if (disposed) return;
			corpus = { kind: 'fallback' };
		}
	}

	function applyJobs(next: IngestionJob[], prior: IngestionJob[]) {
		if (transitionedToDone(prior, next)) void refreshCorpus();
		jobs = next;
		if (selectedId && !next.some((job) => job.id === selectedId)) {
			selectedId = next[0]?.id ?? null;
		}
	}

	async function loadDetail(id: string, seen = epoch) {
		try {
			const detail = await getJob(id);
			if (disposed || seen !== epoch || selectedId !== id) return;
			const prior = jobs;
			applyJobs(replaceJob(jobs, detail), prior);
			detailError = null;
		} catch (error) {
			if (disposed || seen !== epoch || selectedId !== id) return;
			detailError = errorText(error, 'Job detail could not be loaded.');
		}
	}

	async function loadList() {
		const seen = epoch;
		if (jobs.length === 0) listPhase = 'loading';
		try {
			const listed = await listJobs();
			if (disposed || seen !== epoch) return;
			applyJobs(listed, jobs);
			listPhase = 'ready';
			listError = null;
			if (!selectedId) selectedId = listed[0]?.id ?? null;
			if (selectedId) void loadDetail(selectedId, seen);
		} catch (error) {
			if (disposed || seen !== epoch) return;
			listError = errorText(error, 'Ingestion jobs could not be loaded.');
			listPhase = jobs.length === 0 ? 'error' : 'ready';
		}
	}

	async function poll() {
		if (disposed || pollInFlight) return;
		pollInFlight = true;
		const seen = epoch;
		now = Date.now();
		const detailId = selected && isActiveStatus(selected.status) ? selected.id : null;
		try {
			const listed = await listJobs();
			if (disposed || seen !== epoch) return;
			let merged = listed;
			if (detailId) {
				try {
					const detail = await getJob(detailId);
					if (disposed || seen !== epoch) return;
					merged = replaceJob(listed, detail);
					if (selectedId === detailId) detailError = null;
				} catch (error) {
					if (disposed || seen !== epoch) return;
					if (selectedId === detailId) {
						detailError = errorText(error, 'Job detail could not be loaded.');
					}
				}
			}
			applyJobs(merged, jobs);
			listError = null;
			listPhase = 'ready';
		} catch (error) {
			if (disposed || seen !== epoch) return;
			listError = errorText(error, 'Ingestion jobs could not be loaded.');
			if (jobs.length === 0) listPhase = 'error';
		} finally {
			pollInFlight = false;
		}
	}

	async function submitJob(datasetValue: string, slide: string) {
		const path = slide.trim();
		if (!path) {
			formError = 'Enter a GDC diagnostic slide file name (.svs) or file UUID.';
			return;
		}
		const generation = ++submitGeneration;
		epoch += 1;
		submitting = true;
		formError = null;
		try {
			const created = await createJob({ dataset: datasetValue, slide_path: path });
			if (disposed || generation !== submitGeneration) return;
			const effect = interpretSubmit(created);
			if (effect.retryMarkedAt) {
				retriedAt = { ...retriedAt, [created.id]: Date.now() };
			}
			const prior = jobs;
			const next = upsertJob(jobs, created);
			if (effect.refreshCorpus) void refreshCorpus();
			applyJobs(next, prior);
			selectedId = effect.selectJobId;
			notice = effect.notice;
			listError = null;
			detailError = null;
			listPhase = 'ready';
			now = Date.now();
		} catch (error) {
			if (disposed || generation !== submitGeneration) return;
			formError = errorText(error, 'The job could not be queued.');
		} finally {
			if (generation === submitGeneration) submitting = false;
		}
	}

	function selectJob(id: string) {
		if (selectedId !== id) notice = null;
		selectedId = id;
		detailError = null;
		void loadDetail(id);
	}

	function openCase(caseId: string) {
		void goto(resolve('/cases/[caseId]', { caseId }));
	}

	function stageLine(item: (typeof timeline)[number]): string {
		if (item.state === 'completed') {
			const duration =
				item.durationMs === null ? 'Complete' : `${formatDuration(item.durationMs)} · complete`;
			return item.detail ? `${duration} · ${item.detail}` : duration;
		}
		if (item.state === 'active') {
			return item.detail ? `In progress · ${item.detail}` : 'In progress';
		}
		if (item.state === 'failed') {
			const duration =
				item.durationMs === null ? 'Failed' : `${formatDuration(item.durationMs)} · failed`;
			return item.detail ? `${duration} · ${item.detail}` : duration;
		}
		if (item.detail) {
			const duration =
				item.durationMs === null
					? 'Previous attempt'
					: `Previous attempt · ${formatDuration(item.durationMs)}`;
			return `${duration} · ${item.detail}`;
		}
		return 'Waiting';
	}

	$effect(() => {
		const shouldPoll = active;
		if (disposed) {
			scheduler.stop();
			return;
		}
		polling = scheduler.setActive(shouldPoll);
		return () => {
			scheduler.stop();
		};
	});

	onMount(() => {
		void refreshCorpus();
		void loadList();
		return () => {
			disposed = true;
			scheduler.stop();
		};
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
				Queue a TCGA diagnostic slide from the GDC and watch it become searchable precedent.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	<div class="corpus-grid" data-corpus={corpus.kind}>
		{#each corpusStats as stat (stat.label)}
			<div class="surface stat">
				{#if corpus.kind === 'loading'}
					<Skeleton height="lg" width="short" />
				{:else}
					<Typography style="title">{stat.value}</Typography>
				{/if}
				<Typography style="small" tone="muted">{stat.label} loaded</Typography>
			</div>
		{/each}
		<div class="surface corpus-health {corpus.kind}">
			<span class="health-mark"
				><Icon name={corpus.kind === 'fallback' ? 'warning' : 'activity'} /></span
			>
			<div>
				<Typography style="label">
					{corpus.kind === 'ready'
						? 'Corpus counts'
						: corpus.kind === 'loading'
							? 'Checking corpus'
							: 'Counts unavailable'}
				</Typography>
				<Typography style="small" tone="muted">
					{corpus.kind === 'ready'
						? 'Live counts from the health route'
						: corpus.kind === 'loading'
							? 'Asking Postgres for table counts'
							: 'Postgres did not return table counts'}
				</Typography>
			</div>
			{#if corpus.kind === 'fallback'}
				<Button size="sm" variant="secondary" onclick={() => void refreshCorpus()}>Retry</Button>
			{/if}
		</div>
	</div>

	<form
		class="surface new-job"
		aria-busy={submitting}
		onsubmit={(event) => {
			event.preventDefault();
			void submitJob(dataset, slidePath);
		}}
	>
		<div>
			<Typography style="eyebrow" tone="accent">New single-slide job</Typography>
			<Typography as="h2" style="section">Queue from TCGA (GDC)</Typography>
			<Typography style="small" tone="secondary">
				Reference a TCGA project and a GDC diagnostic slide file name or file UUID. The worker
				downloads the file.
			</Typography>
		</div>
		<SelectField bind:value={dataset} label="TCGA project" options={[...COHORT_PROJECTS]} />
		<div class="slide-field">
			<TextField
				bind:value={slidePath}
				label="GDC slide file or UUID"
				placeholder="TCGA-XX-XXXX-01Z-00-DX1.svs or file UUID"
				icon="database"
			/>
			<Typography style="small" tone="muted">
				Diagnostic H&E .svs file name, or the GDC file UUID. This does not upload a slide from the
				browser.
			</Typography>
		</div>
		<Button type="submit" variant="primary" icon="ingest" disabled={submitting}>
			{submitting ? 'Queuing…' : 'Queue ingestion'}
		</Button>
	</form>

	{#if formError}
		<div class="banner">
			<StateMessage tone="danger" title="Job was not queued" description={formError} />
		</div>
	{/if}

	{#if listPhase === 'loading'}
		<div class="pipeline-layout" aria-hidden="true">
			<section class="surface job-list">
				{#each [0, 1, 2] as row (row)}
					<div class="job-skeleton"><Skeleton height="lg" /><Skeleton /></div>
				{/each}
			</section>
			<section class="surface detail-loading">
				<Skeleton height="lg" width="medium" />
				{#each [0, 1, 2, 3, 4, 5] as row (row)}<Skeleton />{/each}
			</section>
		</div>
	{:else if listPhase === 'error' && jobs.length === 0}
		<StateMessage
			tone="danger"
			title="Ingestion jobs could not be loaded"
			description={listError ??
				'Check the API connection, then try again. The form is still available.'}
			action="Retry"
			onaction={() => void loadList()}
		/>
	{:else if jobs.length === 0}
		<section class="surface">
			<EmptyState icon="database" title={EMPTY_JOBS_TITLE} description={EMPTY_JOBS_DESCRIPTION} />
		</section>
	{:else}
		<div class="banners" data-no-worker={noWorker ? 'yes' : 'no'}>
			{#if listError}
				<StateMessage
					tone="danger"
					title="Ingestion jobs could not be loaded"
					description={listError}
					action="Retry"
					onaction={() => void loadList()}
				/>
			{/if}
			{#if noWorker}
				<StateMessage tone="warning" title={NO_WORKER_TITLE} description={NO_WORKER_DESCRIPTION} />
			{/if}
			{#if notice}
				{@const openCaseId = notice.openCaseId}
				<div data-notice={notice.code}>
					<StateMessage
						tone={notice.tone}
						title={notice.title}
						description={notice.description}
						action={openCaseId ? 'Open case' : undefined}
						onaction={openCaseId ? () => openCase(openCaseId) : undefined}
					/>
				</div>
			{/if}
		</div>

		<div class="pipeline-layout" data-polling={polling ? 'on' : 'off'}>
			<section class="surface job-list" aria-label="Recent ingestion jobs">
				<header>
					<div>
						<Typography as="h2" style="section">Recent jobs</Typography>
						<Typography style="small" tone="muted">
							{polling ? 'Checking every few seconds while a job is queued or running' : 'Idle'}
						</Typography>
					</div>
					<Badge tone={polling ? 'info' : 'neutral'}>{polling ? 'Live' : 'Idle'}</Badge>
				</header>
				{#each jobs as job (job.id)}
					<Pressable
						className="job-row"
						selected={job.id === selectedId}
						onclick={() => selectJob(job.id)}
					>
						<div
							class="job-row-top"
							data-job-id={job.id}
							data-selected={job.id === selectedId ? 'yes' : 'no'}
						>
							<Badge tone={statusTone(job.status)}>{job.status}</Badge>
							<Typography style="small" tone="muted">
								Started {formatTimestamp(job.started_at)} · Finished {formatTimestamp(
									job.finished_at
								)}
							</Typography>
						</div>
						<Typography style="label">{job.dataset}</Typography>
						<Typography style="mono" tone="secondary">{job.slide_path}</Typography>
						<div class="meta-row">
							{#if job.requested_by}
								<Avatar name={job.requested_by.name} size="sm" />
								<Typography style="small" tone="muted">{job.requested_by.name}</Typography>
								{#if job.requested_by.is_synthetic}
									<Badge tone="synthetic">Synthetic</Badge>
								{/if}
							{:else}
								<Typography style="small" tone="muted">Requester not recorded</Typography>
							{/if}
							<Typography style="small" tone="muted">{stageLabel(job.stage)}</Typography>
						</div>
					</Pressable>
				{/each}
			</section>

			{#if selected}
				<section class="surface job-detail" aria-live="polite" data-job-status={selected.status}>
					<header>
						<div>
							<Typography style="eyebrow" tone="accent">Selected job</Typography>
							<Typography as="h2" style="section">{selected.slide_path}</Typography>
							<Typography style="small" tone="muted">
								{selected.dataset} · Started {formatTimestamp(selected.started_at)} · Finished
								{formatTimestamp(selected.finished_at)}
							</Typography>
						</div>
						<div class="detail-actions">
							<Badge tone={statusTone(selected.status)}>{selected.status}</Badge>
							{#if selected.status === 'done' && selected.case_id}
								<Button
									size="sm"
									variant="primary"
									onclick={() => openCase(selected.case_id as string)}
								>
									Open case
								</Button>
							{:else if selected.status === 'failed'}
								<Button
									size="sm"
									variant="secondary"
									disabled={submitting}
									onclick={() => void submitJob(selected.dataset, selected.slide_path)}
								>
									Retry
								</Button>
							{/if}
						</div>
					</header>

					{#if detailError}
						<div class="detail-banner">
							<StateMessage
								tone="danger"
								title="Job detail could not be loaded"
								description={detailError}
								action="Retry"
								onaction={() => void loadDetail(selected.id)}
							/>
						</div>
					{/if}

					{#if selected.status === 'failed'}
						<div class="detail-banner" data-failing-stage={selected.stage ?? 'unknown'}>
							<StateMessage
								tone="danger"
								title={failedItem ? `Failed during ${failedItem.label}` : 'Job failed'}
								description={selected.error ??
									'The worker recorded a failure without an error message.'}
							/>
						</div>
					{:else if selected.status === 'running'}
						<div class="detail-banner">
							<StateMessage
								tone="info"
								title="Worker is on this job"
								description={`Current stage: ${stageLabel(selected.stage)}.`}
							/>
						</div>
					{/if}

					<ol class="timeline">
						{#each timeline as item, index (item.stage)}
							<li class="stage {item.state}">
								<span class="stage-marker">{index + 1}</span>
								<div>
									<Typography style="label">{item.label}</Typography>
									<Typography style="small" tone="muted">{stageLine(item)}</Typography>
								</div>
							</li>
						{/each}
					</ol>

					{#if selected.status === 'done' || selected.counts}
						<div class="counts">
							<div>
								<Typography style="title">{formatCount(selected.counts?.patches)}</Typography>
								<Typography style="small" tone="muted">Patches</Typography>
							</div>
							<div>
								<Typography style="title">{formatCount(selected.counts?.chunks)}</Typography>
								<Typography style="small" tone="muted">Report chunks</Typography>
							</div>
						</div>
					{/if}
				</section>
			{/if}
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
		flex: 1;
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
	.corpus-health.fallback .health-mark,
	.corpus-health.loading .health-mark {
		background: var(--color-surface-subtle);
		color: var(--color-text-muted);
	}
	.corpus-health.fallback .health-mark {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	.new-job {
		display: grid;
		grid-template-columns: 1.25fr 1fr 1.5fr auto;
		align-items: end;
		gap: var(--space-4);
		padding: var(--space-5);
		margin-bottom: var(--space-5);
	}
	.new-job > div:first-child,
	.slide-field {
		display: grid;
		gap: var(--space-1);
	}
	.banner,
	.banners {
		display: grid;
		gap: var(--space-3);
		margin-bottom: var(--space-5);
	}
	.pipeline-layout {
		display: grid;
		grid-template-columns: minmax(18rem, 0.85fr) minmax(28rem, 1.4fr);
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
		min-width: 0;
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
	.detail-banner {
		margin: var(--space-5) var(--space-5) 0;
	}
	.timeline {
		display: grid;
		margin: 0;
		padding: var(--space-6);
		list-style: none;
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
		min-width: 0;
	}
	.stage.completed .stage-marker {
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
	.counts {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
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
	.detail-loading,
	.job-skeleton {
		display: grid;
		gap: var(--space-5);
		padding: var(--space-6);
	}
	.job-detail :global(h2) {
		overflow-wrap: anywhere;
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
		.corpus-grid,
		.new-job,
		.pipeline-layout {
			grid-template-columns: 1fr;
		}
	}
</style>
