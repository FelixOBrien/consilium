import { NO_WORKER_AFTER_MS } from './projects.js';
import type { HealthResponse, IngestionJob, JobStatus } from './types.js';

export function statusTone(status: JobStatus): 'info' | 'success' | 'warning' | 'danger' {
	switch (status) {
		case 'queued':
			return 'warning';
		case 'running':
			return 'info';
		case 'done':
			return 'success';
		case 'failed':
			return 'danger';
	}
}

/**
 * A queued job with no worker: `created_at` (or the time this screen retried it)
 * is more than 60 seconds ago.
 */
export function queuedWithoutWorker(
	jobs: readonly Pick<IngestionJob, 'id' | 'status' | 'created_at'>[],
	nowMs: number,
	retriedAtMs: Readonly<Record<string, number>> = {}
): boolean {
	return jobs.some((job) => {
		if (job.status !== 'queued') return false;
		const since = retriedAtMs[job.id] ?? Date.parse(job.created_at);
		if (Number.isNaN(since)) return false;
		return nowMs - since > NO_WORKER_AFTER_MS;
	});
}

export type SubmitNotice = {
	code: 'retried' | 'duplicate_active' | 'already_ingested';
	jobId: string;
	tone: 'info' | 'warning' | 'success';
	title: string;
	description: string;
	openCaseId: string | null;
};

export type SubmitEffect = {
	selectJobId: string;
	notice: SubmitNotice | null;
	refreshCorpus: boolean;
	retryMarkedAt: boolean;
};

/** What S-08 should do with the body of `POST /api/ingestion/jobs`. */
export function interpretSubmit(job: IngestionJob): SubmitEffect {
	switch (job.outcome) {
		case 'retried':
			return {
				selectJobId: job.id,
				refreshCorpus: false,
				retryMarkedAt: true,
				notice: {
					code: 'retried',
					jobId: job.id,
					tone: 'info',
					title: 'Job queued again',
					description: 'The failed job is back on the queue. Its stage history is unchanged.',
					openCaseId: null
				}
			};
		case 'duplicate_active':
			return {
				selectJobId: job.id,
				refreshCorpus: false,
				retryMarkedAt: false,
				notice: {
					code: 'duplicate_active',
					jobId: job.id,
					tone: 'warning',
					title: 'This slide already has an active job',
					description:
						'The existing queued or running job is selected. Another job was not created.',
					openCaseId: null
				}
			};
		case 'already_ingested':
			return {
				selectJobId: job.id,
				refreshCorpus: true,
				retryMarkedAt: false,
				notice: {
					code: 'already_ingested',
					jobId: job.id,
					tone: 'success',
					title: 'This slide is already ingested',
					description:
						'The slide is already ready, so nothing new was queued. Open the case to view it.',
					openCaseId: job.case_id
				}
			};
		case 'created':
		case null:
		case undefined:
			return {
				selectJobId: job.id,
				notice: null,
				refreshCorpus: false,
				retryMarkedAt: false
			};
	}
}

/** True when a job that was queued or running is now done. */
export function transitionedToDone(
	previous: readonly Pick<IngestionJob, 'id' | 'status'>[],
	next: readonly Pick<IngestionJob, 'id' | 'status'>[]
): boolean {
	const prior = new Map(previous.map((job) => [job.id, job.status]));
	return next.some((job) => {
		const before = prior.get(job.id);
		return job.status === 'done' && (before === 'queued' || before === 'running');
	});
}

export function compareJobsDesc(
	a: Pick<IngestionJob, 'id' | 'created_at'>,
	b: Pick<IngestionJob, 'id' | 'created_at'>
): number {
	const byTime = Date.parse(b.created_at) - Date.parse(a.created_at);
	if (!Number.isNaN(byTime) && byTime !== 0) return byTime;
	if (a.id === b.id) return 0;
	return a.id < b.id ? 1 : -1;
}

export function upsertJob(jobs: readonly IngestionJob[], job: IngestionJob): IngestionJob[] {
	return [...jobs.filter((item) => item.id !== job.id), job].sort(compareJobsDesc);
}

export function replaceJob(jobs: readonly IngestionJob[], job: IngestionJob): IngestionJob[] {
	const index = jobs.findIndex((item) => item.id === job.id);
	if (index === -1) return upsertJob(jobs, job);
	const next = jobs.slice();
	next[index] = job;
	return next;
}

export type CorpusSnapshot =
	| { kind: 'loading' }
	| { kind: 'fallback' }
	| { kind: 'ready'; cases: number; slides: number; patches: number; reportChunks: number };

export function corpusFromHealth(health: HealthResponse): CorpusSnapshot {
	const { cases, slides, patches, report_chunks: reportChunks } = health;
	if (cases == null || slides == null || patches == null || reportChunks == null) {
		return { kind: 'fallback' };
	}
	return { kind: 'ready', cases, slides, patches, reportChunks };
}
