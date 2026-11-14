import type { components } from '#lib/api/schema.js';

/** Generated API shapes. Do not hand-write response fields. */
export type PatientDetail = components['schemas']['PatientDetail'];
export type PatientSummary = components['schemas']['PatientSummary'];
export type CaseSummary = components['schemas']['CaseSummary'];
export type CaseStatus = components['schemas']['CaseStatus'];
export type Specialty = components['schemas']['Specialty'];
export type Sex = components['schemas']['Sex'];
export type ReportSection = components['schemas']['ReportSection'];
export type ReportSearchRequest = components['schemas']['ReportSearchRequest'];
export type PatchSearchRequest = components['schemas']['PatchSearchRequest'];

export type PatientSearchMode = 'reports' | 'tissue';

/** Level-0 patch passed to `casePeek.open`. */
export type PeekPatch = {
	id: string;
	slide_id: string;
	x: number;
	y: number;
	size?: number;
};
