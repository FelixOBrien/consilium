/** Cohort projects from `PROJECT_SPECIALTY` in the pipeline. Order matches that map. */
export const COHORT_PROJECTS = [
	'TCGA-BRCA',
	'TCGA-LUAD',
	'TCGA-LUSC',
	'TCGA-COAD',
	'TCGA-READ',
	'TCGA-STAD',
	'TCGA-ESCA',
	'TCGA-SKCM',
	'TCGA-DLBC'
] as const;

export type CohortProject = (typeof COHORT_PROJECTS)[number];

export const WORKER_COMMAND = 'uv run consilium pipeline worker'; // pragma: allowlist secret

export const NO_WORKER_AFTER_MS = 60_000;

export const NO_WORKER_TITLE = 'No worker appears to be running';

export const NO_WORKER_DESCRIPTION = `A job has been queued for more than a minute. Start the worker on the machine that can reach Postgres and the GDC: ${WORKER_COMMAND}`;

export const EMPTY_JOBS_TITLE = 'No ingestion jobs yet';

export const EMPTY_JOBS_DESCRIPTION = `Nothing has been queued. A job needs a TCGA project and a GDC diagnostic .svs file name or file UUID, plus a running worker: ${WORKER_COMMAND}`;
