import { describe, expect, test } from 'bun:test';
import { formatCount, formatDuration } from './format.js';
import {
	corpusFromHealth,
	interpretSubmit,
	queuedWithoutWorker,
	transitionedToDone,
	upsertJob
} from './outcomes.js';
import { createPollScheduler, hasActiveJob, POLL_INTERVAL_MS, pollPhase } from './polling.js';
import { NO_WORKER_AFTER_MS, NO_WORKER_DESCRIPTION, WORKER_COMMAND } from './projects.js';
import { deriveTimeline, PIPELINE_STAGES } from './timeline.js';
import type { IngestionJob, StageName, StageRecord } from './types.js';

const T0 = '2026-11-15T12:00:00.000Z';
const T1 = '2026-11-15T12:00:30.000Z';
const T2 = '2026-11-15T12:01:00.000Z';
const T3 = '2026-11-15T12:02:30.000Z';

function record(
	stage: StageName,
	startedAt: string,
	finishedAt: string | null,
	detail: string | null = null
): StageRecord {
	return { stage, started_at: startedAt, finished_at: finishedAt, detail };
}

function job(overrides: Partial<IngestionJob> = {}): IngestionJob {
	return {
		id: '00000000-0000-4000-8000-000000000001',
		dataset: 'TCGA-BRCA',
		slide_path: 'TCGA-AA-0001-01Z-00-DX1.svs',
		case_id: null,
		slide_id: null,
		requested_by: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			primary_specialty: 'breast',
			is_synthetic: true
		},
		status: 'queued',
		stage: null,
		stage_history: [],
		counts: null,
		error: null,
		attempts: 0,
		created_at: T0,
		started_at: null,
		finished_at: null,
		outcome: null,
		...overrides
	};
}

describe('polling state machine', () => {
	test('stays idle with no jobs and starts a single timer only while work is active', () => {
		const handles: { id: number; ms: number }[] = [];
		const cleared: number[] = [];
		let nextId = 1;
		let ticks = 0;
		const scheduler = createPollScheduler({
			onTick: () => {
				ticks += 1;
			},
			timer: {
				set(_callback, intervalMs) {
					const id = nextId;
					nextId += 1;
					handles.push({ id, ms: intervalMs });
					return id;
				},
				clear(handle) {
					cleared.push(handle as number);
				}
			}
		});

		expect(pollPhase([])).toBe('idle');
		expect(scheduler.sync([])).toBe(false);
		expect(scheduler.running()).toBe(false);
		expect(handles).toHaveLength(0);

		expect(hasActiveJob([{ status: 'done' }, { status: 'failed' }])).toBe(false);
		expect(scheduler.sync([{ status: 'queued' }, { status: 'done' }])).toBe(true);
		expect(scheduler.sync([{ status: 'running' }])).toBe(true);
		expect(handles).toEqual([{ id: 1, ms: POLL_INTERVAL_MS }]);
		expect(scheduler.phase()).toBe('active');
		expect(cleared).toEqual([]);

		expect(scheduler.sync([{ status: 'done' }, { status: 'failed' }])).toBe(false);
		expect(scheduler.running()).toBe(false);
		expect(scheduler.phase()).toBe('idle');
		expect(cleared).toEqual([1]);
		expect(ticks).toBe(0);
	});

	test('stop clears the timer and a later active job can start again', () => {
		const cleared: number[] = [];
		let nextId = 1;
		const scheduler = createPollScheduler({
			onTick: () => undefined,
			timer: {
				set() {
					const id = nextId;
					nextId += 1;
					return id;
				},
				clear(handle) {
					cleared.push(handle as number);
				}
			}
		});

		scheduler.setActive(true);
		scheduler.stop();
		expect(scheduler.running()).toBe(false);
		expect(cleared).toEqual([1]);

		expect(scheduler.sync([{ status: 'running' }])).toBe(true);
		expect(scheduler.running()).toBe(true);
		scheduler.stop();
		expect(cleared).toEqual([1, 2]);
		expect(scheduler.running()).toBe(false);
	});
});

describe('queued with no worker', () => {
	test('is true only after a queued job has waited more than 60 seconds', () => {
		const created = Date.parse('2026-11-15T12:00:00.000Z');
		const queued = job({ status: 'queued', created_at: '2026-11-15T12:00:00.000Z' });
		expect(queuedWithoutWorker([queued], created + NO_WORKER_AFTER_MS)).toBe(false);
		expect(queuedWithoutWorker([queued], created + NO_WORKER_AFTER_MS + 1)).toBe(true);
		expect(
			queuedWithoutWorker(
				[job({ status: 'running', created_at: '2026-11-01T00:00:00.000Z' })],
				created + NO_WORKER_AFTER_MS + 1
			)
		).toBe(false);
		expect(NO_WORKER_DESCRIPTION).toContain(WORKER_COMMAND);
	});

	test('uses the retry time instead of the original created_at', () => {
		const created = Date.parse('2026-11-01T00:00:00.000Z');
		const retriedAt = Date.parse('2026-11-15T12:00:00.000Z');
		const queued = job({
			id: 'job-retry',
			status: 'queued',
			created_at: '2026-11-01T00:00:00.000Z'
		});
		const clock = { 'job-retry': retriedAt };
		expect(queuedWithoutWorker([queued], created + NO_WORKER_AFTER_MS + 1, clock)).toBe(false);
		expect(queuedWithoutWorker([queued], retriedAt + NO_WORKER_AFTER_MS, clock)).toBe(false);
		expect(queuedWithoutWorker([queued], retriedAt + NO_WORKER_AFTER_MS + 1, clock)).toBe(true);
	});
});

describe('stage timeline', () => {
	test('a queued retry stays pending and still shows the kept history detail', () => {
		const items = deriveTimeline(
			job({
				status: 'queued',
				stage: null,
				stage_history: [record('embed', T0, T1, 'fixture failure')]
			})
		);
		const embed = items.find((item) => item.stage === 'embed');
		expect(embed?.state).toBe('pending');
		expect(embed?.detail).toBe('fixture failure');
		expect(embed?.durationMs).toBe(30_000);
		expect(items.filter((item) => item.state !== 'pending')).toHaveLength(0);
	});

	test('lists every pipeline stage as pending while the job is queued', () => {
		const items = deriveTimeline(job());
		expect(items.map((item) => item.stage)).toEqual([...PIPELINE_STAGES]);
		expect(items.every((item) => item.state === 'pending')).toBe(true);
		expect(PIPELINE_STAGES).toHaveLength(8);
	});

	test('marks the current stage active and completed stages with duration and detail', () => {
		const items = deriveTimeline(
			job({
				status: 'running',
				stage: 'embed',
				started_at: T0,
				stage_history: [
					record('download', T0, T1, 'file saved'),
					record('segment', T1, T2, 'tissue mask'),
					record('embed', T2, null, '12,840 patches')
				]
			})
		);
		const byStage = Object.fromEntries(items.map((item) => [item.stage, item]));
		expect(byStage.download?.state).toBe('completed');
		expect(byStage.download?.durationMs).toBe(30_000);
		expect(byStage.download?.detail).toBe('file saved');
		expect(byStage.segment?.state).toBe('completed');
		expect(byStage.segment?.durationMs).toBe(30_000);
		expect(byStage.embed?.state).toBe('active');
		expect(byStage.embed?.durationMs).toBeNull();
		expect(byStage.embed?.detail).toBe('12,840 patches');
		expect(byStage.project?.state).toBe('pending');
		expect(byStage.index?.state).toBe('pending');
	});

	test('marks the failing stage failed even when its history row has finished', () => {
		const items = deriveTimeline(
			job({
				status: 'failed',
				stage: 'embed',
				error: 'slide resolution metadata was unavailable',
				stage_history: [
					record('download', T0, T1, 'file saved'),
					record('embed', T2, T3, 'slide resolution metadata was unavailable')
				]
			})
		);
		const embed = items.find((item) => item.stage === 'embed');
		const download = items.find((item) => item.stage === 'download');
		const project = items.find((item) => item.stage === 'project');
		expect(embed?.state).toBe('failed');
		expect(embed?.durationMs).toBe(90_000);
		expect(embed?.detail).toBe('slide resolution metadata was unavailable');
		expect(download?.state).toBe('completed');
		expect(project?.state).toBe('pending');
	});

	test('uses the latest history row when a stage is recorded twice', () => {
		const items = deriveTimeline(
			job({
				status: 'running',
				stage: 'segment',
				stage_history: [
					record('download', T0, T1, 'first attempt'),
					record('download', T2, T3, 'retried download')
				]
			})
		);
		const download = items.find((item) => item.stage === 'download');
		expect(download?.detail).toBe('retried download');
		expect(download?.state).toBe('completed');
		expect(download?.durationMs).toBe(90_000);
		expect(items.find((item) => item.stage === 'segment')?.state).toBe('active');
	});

	test('shows completed stages for a finished job and leaves stages that never ran pending', () => {
		const items = deriveTimeline(
			job({
				status: 'done',
				stage: 'index',
				stage_history: [record('download', T0, T1, 'cached'), record('index', T2, T3, 'analyzed')]
			})
		);
		expect(items.find((item) => item.stage === 'download')?.state).toBe('completed');
		expect(items.find((item) => item.stage === 'index')?.state).toBe('completed');
		expect(items.find((item) => item.stage === 'segment')?.state).toBe('pending');
	});
});

describe('submit outcomes', () => {
	test('created selects the new job and does not raise a notice', () => {
		const created = job({ outcome: 'created' });
		expect(interpretSubmit(created)).toEqual({
			selectJobId: created.id,
			notice: null,
			refreshCorpus: false,
			retryMarkedAt: false
		});
	});

	test('retried keeps the same job selected and asks the screen to time the queue from now', () => {
		const effect = interpretSubmit(job({ outcome: 'retried', status: 'queued' }));
		expect(effect.retryMarkedAt).toBe(true);
		expect(effect.refreshCorpus).toBe(false);
		expect(effect.notice?.code).toBe('retried');
		expect(effect.notice?.title).toBe('Job queued again');
		expect(effect.selectJobId).toBe(job().id);
	});

	test('duplicate_active selects the existing job and explains that nothing new was created', () => {
		const effect = interpretSubmit(
			job({ id: 'active-job', outcome: 'duplicate_active', status: 'running', stage: 'project' })
		);
		expect(effect.selectJobId).toBe('active-job');
		expect(effect.refreshCorpus).toBe(false);
		expect(effect.retryMarkedAt).toBe(false);
		expect(effect.notice?.code).toBe('duplicate_active');
		expect(effect.notice?.tone).toBe('warning');
		expect(effect.notice?.title).toBe('This slide already has an active job');
		expect(effect.notice?.openCaseId).toBeNull();
	});

	test('already_ingested offers the case and refreshes corpus counts', () => {
		const effect = interpretSubmit(
			job({
				outcome: 'already_ingested',
				status: 'done',
				case_id: 'FX-B042A',
				counts: { patches: 12, chunks: 4 }
			})
		);
		expect(effect.refreshCorpus).toBe(true);
		expect(effect.notice?.code).toBe('already_ingested');
		expect(effect.notice?.tone).toBe('success');
		expect(effect.notice?.title).toBe('This slide is already ingested');
		expect(effect.notice?.openCaseId).toBe('FX-B042A');
	});

	test('a missing outcome is treated as a new job', () => {
		const effect = interpretSubmit(job({ outcome: null }));
		expect(effect.notice).toBeNull();
		expect(effect.selectJobId).toBe(job().id);
	});
});

describe('corpus and job list helpers', () => {
	test('refreshes counts only when an active job becomes done', () => {
		const queued = job({ status: 'queued' });
		const running = job({ status: 'running', stage: 'load' });
		const done = job({ status: 'done', stage: 'index' });
		expect(transitionedToDone([queued], [running])).toBe(false);
		expect(transitionedToDone([queued], [done])).toBe(true);
		expect(transitionedToDone([running], [done])).toBe(true);
		expect(transitionedToDone([done], [done])).toBe(false);
		expect(transitionedToDone([], [done])).toBe(false);
	});

	test('places a newly queued job ahead of older ones and replaces the same id', () => {
		const older = job({ id: 'older', created_at: '2026-11-01T00:00:00.000Z' });
		const newer = job({ id: 'newer', created_at: '2026-11-15T00:00:00.000Z', status: 'done' });
		const updated = job({
			id: 'older',
			created_at: older.created_at,
			status: 'running',
			stage: 'download'
		});
		expect(upsertJob([older], newer).map((item) => item.id)).toEqual(['newer', 'older']);
		expect(upsertJob([older, newer], updated).map((item) => item.status)).toEqual([
			'done',
			'running'
		]);
	});

	test('corpus snapshot falls back when health omits table counts', () => {
		expect(corpusFromHealth({ status: 'ok' })).toEqual({ kind: 'fallback' });
		expect(
			corpusFromHealth({ status: 'ok', cases: 12, slides: 12, patches: 40, report_chunks: 80 })
		).toEqual({ kind: 'ready', cases: 12, slides: 12, patches: 40, reportChunks: 80 });
	});

	test('formats durations and counts without a clinical claim', () => {
		expect(formatDuration(0)).toBe('0s');
		expect(formatDuration(90_000)).toBe('1m 30s');
		expect(formatDuration(3_600_000)).toBe('1h');
		expect(formatCount(null)).toBe('—');
		expect(formatCount(1200)).toBe('1,200');
	});
});
