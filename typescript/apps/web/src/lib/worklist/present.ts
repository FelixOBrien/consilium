import type { CaseSummary, CaseStatus, Specialty } from './query.js';
import { specialtyLabel, statusLabel } from './query.js';

export type CaseRow = {
	id: string;
	caseHref: string;
	specialty: Specialty;
	specialtyLabel: string;
	patientId: string;
	patientLabel: string;
	patientHref: string;
	patientCaseCount: number;
	priorCases: boolean;
	ageSex: string;
	status: CaseStatus;
	statusLabel: string;
	pathologistId: string;
	pathologistName: string;
	pathologistSynthetic: boolean;
	slideCount: number;
	icd10: string | null;
	accessioned: string;
	thumbnailUrl: string | null;
	/** Signed-out precedent only. Open cases never surface a conclusion (F-01.3). */
	conclusion: string | null;
};

export function visibleConclusion(
	item: Pick<CaseSummary, 'status' | 'conclusion_line'>
): string | null {
	if (item.status !== 'signed_out') return null;
	const line = item.conclusion_line?.trim() ?? '';
	return line || null;
}

export function formatAgeSex(age: number | null | undefined, sex: 'F' | 'M' | null): string {
	const sexLabel = sex === 'F' ? 'Female' : sex === 'M' ? 'Male' : null;
	if (age != null && sexLabel) return `${age} years · ${sexLabel}`;
	if (age != null) return `${age} years`;
	if (sexLabel) return sexLabel;
	return 'Age and sex not recorded';
}

export function formatAccessioned(iso: string): string {
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	return new Intl.DateTimeFormat('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric',
		timeZone: 'UTC'
	}).format(date);
}

export function presentCase(item: CaseSummary): CaseRow {
	return {
		id: item.id,
		caseHref: `/cases/${item.id}`,
		specialty: item.specialty,
		specialtyLabel: specialtyLabel(item.specialty),
		patientId: item.patient.id,
		patientLabel: item.patient.display_label,
		patientHref: `/patients/${item.patient.id}`,
		patientCaseCount: item.patient.case_count,
		priorCases: item.patient.case_count > 1,
		ageSex: formatAgeSex(item.patient_age, item.patient_sex),
		status: item.status,
		statusLabel: statusLabel(item.status),
		pathologistId: item.assigned_to.id,
		pathologistName: item.assigned_to.name,
		pathologistSynthetic: item.assigned_to.is_synthetic,
		slideCount: item.slide_count,
		icd10: item.icd10,
		accessioned: formatAccessioned(item.accessioned_at),
		thumbnailUrl: item.thumbnail_url,
		conclusion: visibleConclusion(item)
	};
}

export function appendCases(current: CaseSummary[], page: CaseSummary[]): CaseSummary[] {
	const seen = new Set(current.map((item) => item.id));
	const added = page.filter((item) => !seen.has(item.id));
	return added.length === 0 ? current : [...current, ...added];
}
