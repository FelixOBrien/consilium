import type { components } from '#lib/api/schema.js';

/** Aliases of the generated OpenAPI types. Do not restate these shapes by hand. */
export type IngestionJob = components['schemas']['IngestionJob'];
export type IngestionJobCreate = components['schemas']['IngestionJobCreate'];
export type StageRecord = components['schemas']['StageRecord'];
export type HealthResponse = components['schemas']['HealthResponse'];
export type StageName = NonNullable<IngestionJob['stage']>;
export type JobStatus = IngestionJob['status'];
export type JobOutcome = NonNullable<IngestionJob['outcome']>;
