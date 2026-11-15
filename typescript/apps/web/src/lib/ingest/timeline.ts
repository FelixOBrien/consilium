import type { IngestionJob, StageName, StageRecord } from './types.js';

const STAGE_LABELS = {
	download: 'Download slide',
	segment: 'Segment tissue',
	embed: 'Embed patches',
	project: 'Project features',
	thumbnails: 'Build thumbnails',
	reports: 'Process reports',
	load: 'Load database',
	index: 'Build indexes'
} as const satisfies Record<StageName, string>;

/** Pipeline order. The label map is `Record<StageName, …>`, so a new API stage fails the build. */
export const PIPELINE_STAGES = [
	'download',
	'segment',
	'embed',
	'project',
	'thumbnails',
	'reports',
	'load',
	'index'
] as const satisfies readonly StageName[];

export type StageVisual = 'pending' | 'active' | 'completed' | 'failed';

export type StageTimelineItem = {
	stage: StageName;
	label: string;
	state: StageVisual;
	startedAt: string | null;
	finishedAt: string | null;
	durationMs: number | null;
	detail: string | null;
};

export function stageLabel(stage: StageName | null): string {
	if (!stage) return 'Waiting to start';
	return STAGE_LABELS[stage];
}

export function stageDurationMs(
	startedAt: string | null,
	finishedAt: string | null
): number | null {
	if (!startedAt || !finishedAt) return null;
	const started = Date.parse(startedAt);
	const finished = Date.parse(finishedAt);
	if (Number.isNaN(started) || Number.isNaN(finished) || finished < started) return null;
	return finished - started;
}

function latestByStage(history: readonly StageRecord[]): Map<StageName, StageRecord> {
	const map = new Map<StageName, StageRecord>();
	for (const record of history) {
		if (record.stage in STAGE_LABELS) map.set(record.stage, record);
	}
	return map;
}

function visualState(
	job: Pick<IngestionJob, 'status' | 'stage'>,
	stage: StageName,
	record: StageRecord | undefined
): StageVisual {
	// A retry is queued again with the old history kept. This attempt has not started.
	if (job.status === 'queued') return 'pending';
	if (job.status === 'failed' && job.stage === stage) return 'failed';
	if (job.status === 'running' && job.stage === stage) return 'active';
	if (record?.finished_at) return 'completed';
	if (job.status === 'done' && job.stage === stage) return 'completed';
	return 'pending';
}

/** Ordered stages from `stage_history`, the current `stage`, and `status`. */
export function deriveTimeline(
	job: Pick<IngestionJob, 'status' | 'stage' | 'stage_history'>
): StageTimelineItem[] {
	const history = latestByStage(job.stage_history);
	return PIPELINE_STAGES.map((stage) => {
		const record = history.get(stage);
		const state = visualState(job, stage, record);
		const startedAt = record?.started_at ?? null;
		const finishedAt = record?.finished_at ?? null;
		return {
			stage,
			label: STAGE_LABELS[stage],
			state,
			startedAt,
			finishedAt,
			durationMs: state === 'active' ? null : stageDurationMs(startedAt, finishedAt),
			detail: record?.detail ?? null
		};
	});
}
