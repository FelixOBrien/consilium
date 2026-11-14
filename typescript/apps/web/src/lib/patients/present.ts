import type { CaseHit } from './load.js';
import type {
	CaseStatus,
	CaseSummary,
	PatientDetail,
	PatientSearchMode,
	PatientSummary,
	PeekPatch,
	ReportSection,
	Sex,
	Specialty
} from './types.js';

export const NOT_YET_REPORTED = 'Not yet reported';
export const SIGNED_OUT = 'Signed out';
export const SYNTHETIC_PATIENT_LINKAGE = 'Synthetic patient linkage';
export const SYNTHETIC_LINKAGE = 'Synthetic linkage';
export const SINGLE_CASE_NOTE = 'No prior specimens are recorded for this patient.';
export const PATCHES_PER_HIT = 3;

const SPECIALTY_LABEL: Record<Specialty, string> = {
	breast: 'Breast',
	thorax: 'Thoracic',
	colorectal: 'Colorectal',
	gastrointestinal: 'Gastrointestinal',
	hematologic: 'Hematologic',
	skin: 'Skin'
};

const SECTION_LABEL: Record<ReportSection, string> = {
	clinical_history: 'Clinical history',
	gross_description: 'Gross description',
	microscopic_description: 'Microscopic description',
	conclusion: 'Conclusion',
	additional_info: 'Additional information',
	body: 'Report'
};

export type TextSegment = {
	text: string;
	highlighted: boolean;
};

export type DirectoryRow = {
	id: string;
	href: string;
	displayLabel: string;
	sexSummary: string;
	caseCount: number;
	openCount: number;
	signedOutCount: number;
	specialties: string;
	latestAccessioned: string;
	syntheticLinkage: boolean;
};

export type PatientHeaderView = {
	id: string;
	displayLabel: string;
	sex: string;
	birthYear: string;
	caseCount: number;
	openCount: number;
	signedOutCount: number;
	specialties: string;
	syntheticLinkage: boolean;
	singleCase: boolean;
	timelineNote: string;
};

export type TimelineCaseView = {
	id: string;
	specimenLabel: string;
	specialtyLabel: string;
	ageAtAccession: string;
	accessioned: string;
	slideCount: number;
	slideLabel: string;
	thumbnailUrl: string | null;
	status: CaseStatus;
	statusLabel: string;
	/** Null for every open case, even if the payload included a code. */
	icd10: string | null;
	/** Null for every open case, even if the payload included a line. */
	conclusion: string | null;
	pathologistId: string;
	pathologistName: string;
	pathologistSynthetic: boolean;
	pathologistRole: 'Assigned to' | 'Reported by';
	pathologistHref: string;
	openHref: string;
	consultHref: string | null;
};

export type SearchPatchView = {
	id: string;
	slideId: string;
	x: number;
	y: number;
	size: number;
	thumbnailUrl: string;
	peek: PeekPatch;
};

export type SearchHitView = {
	caseId: string;
	specimenLabel: string;
	specialtyLabel: string;
	accessioned: string;
	icd10: string | null;
	authorName: string;
	authorSynthetic: boolean;
	authorHref: string;
	passage: { sectionLabel: string; segments: TextSegment[] } | null;
	patches: SearchPatchView[];
	openHref: string;
	peekPatch: PeekPatch | null;
};

export function specialtyLabel(specialty: string): string {
	return SPECIALTY_LABEL[specialty as Specialty] ?? specialty;
}

export function formatSex(sex: Sex | null | undefined): string {
	if (sex === 'F') return 'Female';
	if (sex === 'M') return 'Male';
	return 'Sex not recorded';
}

export function formatBirthYear(year: number | null | undefined): string {
	if (year == null) return 'Birth year not recorded';
	return `Approx. birth year ${year}`;
}

export function formatAge(age: number | null | undefined): string {
	if (age == null) return 'Age at accession not recorded';
	return `${age} years`;
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

export function formatSlideCount(count: number): string {
	return `${count} ${count === 1 ? 'slide' : 'slides'}`;
}

export function caseStatusLabel(status: CaseStatus): string {
	return status === 'open' ? NOT_YET_REPORTED : SIGNED_OUT;
}

/**
 * Open cases never surface a conclusion. A leaked line in the payload is dropped.
 */
export function visibleConclusion(
	item: Pick<CaseSummary, 'status' | 'conclusion_line'>
): string | null {
	if (item.status !== 'signed_out') return null;
	const line = item.conclusion_line?.trim() ?? '';
	return line || null;
}

/** Open cases never surface ICD-10. A leaked code in the payload is dropped. */
export function visibleIcd10(item: Pick<CaseSummary, 'status' | 'icd10'>): string | null {
	if (item.status !== 'signed_out') return null;
	const code = item.icd10?.trim() ?? '';
	return code || null;
}

export function patientHref(patientId: string): string {
	return `/patients/${encodeURIComponent(patientId)}`;
}

export function caseHref(caseId: string, query?: Record<string, string>): string {
	const path = `/cases/${encodeURIComponent(caseId)}`;
	if (!query) return path;
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(query)) {
		if (value) params.set(key, value);
	}
	const text = params.toString();
	return text ? `${path}?${text}` : path;
}

/** S-01 filtered to that pathologist's signed-out cases. */
export function pathologistSignedOutHref(pathologistId: string): string {
	const params = new URLSearchParams({
		view: 'all',
		status: 'signed_out',
		assigned_to: pathologistId
	});
	return `/?${params.toString()}`;
}

export function corpusSearchHref(text: string, mode: PatientSearchMode): string {
	const params = new URLSearchParams({ q: text, mode });
	return `/search?${params.toString()}`;
}

export function formatSpecialties(specialties: readonly string[]): string {
	if (specialties.length === 0) return 'No specialty recorded';
	return specialties.map((specialty) => specialtyLabel(specialty)).join(' · ');
}

export function presentDirectoryRow(patient: PatientSummary): DirectoryRow {
	return {
		id: patient.id,
		href: patientHref(patient.id),
		displayLabel: patient.display_label,
		sexSummary: formatSex(patient.sex),
		caseCount: patient.case_count,
		openCount: patient.open_case_count,
		signedOutCount: patient.signed_out_case_count,
		specialties: formatSpecialties(patient.specialties),
		latestAccessioned: formatAccessioned(patient.latest_accessioned_at),
		syntheticLinkage: patient.is_synthetic_linkage
	};
}

export function presentPatient(detail: PatientDetail): PatientHeaderView {
	const singleCase = detail.case_count <= 1;
	return {
		id: detail.id,
		displayLabel: detail.display_label,
		sex: formatSex(detail.sex),
		birthYear: formatBirthYear(detail.birth_year),
		caseCount: detail.case_count,
		openCount: detail.open_case_count,
		signedOutCount: detail.signed_out_case_count,
		specialties: formatSpecialties(detail.specialties),
		syntheticLinkage: detail.is_synthetic_linkage,
		singleCase,
		timelineNote: singleCase ? SINGLE_CASE_NOTE : `${detail.case_count} cases, newest first.`
	};
}

export function chronologicalCases(cases: readonly CaseSummary[]): CaseSummary[] {
	return [...cases].sort((a, b) => {
		const time = Date.parse(b.accessioned_at) - Date.parse(a.accessioned_at);
		if (time !== 0 && Number.isFinite(time)) return time;
		if (a.id < b.id) return -1;
		if (a.id > b.id) return 1;
		return 0;
	});
}

export function presentTimelineCase(item: CaseSummary, signedOutCount: number): TimelineCaseView {
	const signedOut = item.status === 'signed_out';
	return {
		id: item.id,
		specimenLabel: item.specimen_label?.trim() || 'Specimen not labelled',
		specialtyLabel: specialtyLabel(item.specialty),
		ageAtAccession: formatAge(item.patient_age),
		accessioned: formatAccessioned(item.accessioned_at),
		slideCount: item.slide_count,
		slideLabel: formatSlideCount(item.slide_count),
		thumbnailUrl: item.thumbnail_url,
		status: item.status,
		statusLabel: caseStatusLabel(item.status),
		icd10: visibleIcd10(item),
		conclusion: visibleConclusion(item),
		pathologistId: item.assigned_to.id,
		pathologistName: item.assigned_to.name,
		pathologistSynthetic: item.assigned_to.is_synthetic,
		pathologistRole: signedOut ? 'Reported by' : 'Assigned to',
		pathologistHref: pathologistSignedOutHref(item.assigned_to.id),
		openHref: caseHref(item.id),
		consultHref:
			item.status === 'open' && signedOutCount > 0 ? caseHref(item.id, { panel: 'consult' }) : null
	};
}

export function presentTimeline(detail: PatientDetail): TimelineCaseView[] {
	return chronologicalCases(detail.cases).map((item) =>
		presentTimelineCase(item, detail.signed_out_case_count)
	);
}

export function highlightSegments(
	text: string,
	highlights: ReadonlyArray<readonly number[]>
): TextSegment[] {
	const ranges: { start: number; end: number }[] = [];
	for (const range of highlights) {
		const rawStart = range[0];
		const rawEnd = range[1];
		if (rawStart === undefined || rawEnd === undefined) continue;
		if (!Number.isInteger(rawStart) || !Number.isInteger(rawEnd)) continue;
		const start = Math.max(0, rawStart);
		const end = Math.min(text.length, rawEnd);
		if (start >= end) continue;
		ranges.push({ start, end });
	}
	ranges.sort((a, b) => a.start - b.start || a.end - b.end);
	const merged: { start: number; end: number }[] = [];
	for (const range of ranges) {
		const last = merged[merged.length - 1];
		if (!last || range.start > last.end) merged.push({ ...range });
		else last.end = Math.max(last.end, range.end);
	}
	const segments: TextSegment[] = [];
	let cursor = 0;
	for (const range of merged) {
		if (range.start > cursor) {
			segments.push({ text: text.slice(cursor, range.start), highlighted: false });
		}
		segments.push({ text: text.slice(range.start, range.end), highlighted: true });
		cursor = range.end;
	}
	if (cursor < text.length) segments.push({ text: text.slice(cursor), highlighted: false });
	if (segments.length === 0 && text) segments.push({ text, highlighted: false });
	return segments;
}

function presentPassage(
	passage: CaseHit['passage']
): { sectionLabel: string; segments: TextSegment[] } | null {
	if (!passage) return null;
	const text = passage.text ?? '';
	if (!text) return null;
	return {
		sectionLabel: SECTION_LABEL[passage.section] ?? 'Report',
		segments: highlightSegments(text, passage.highlights ?? [])
	};
}

function presentPatch(patch: CaseHit['patches'][number]): SearchPatchView {
	const peek: PeekPatch = {
		id: String(patch.patch_id),
		slide_id: patch.slide_id,
		x: patch.x,
		y: patch.y,
		size: patch.size
	};
	return {
		id: peek.id,
		slideId: patch.slide_id,
		x: patch.x,
		y: patch.y,
		size: patch.size,
		thumbnailUrl: patch.thumbnail_url,
		peek
	};
}

/**
 * Drops open cases and any hit that belongs to a different patient.
 * Report body is never copied; tissue hits keep thumbnails only.
 */
export function presentSearchHits(
	patientId: string,
	mode: PatientSearchMode,
	hits: readonly CaseHit[]
): SearchHitView[] {
	const views: SearchHitView[] = [];
	for (const hit of hits) {
		if (hit.case.status !== 'signed_out') continue;
		if (hit.case.patient.id !== patientId) continue;
		const patches =
			mode === 'tissue' ? hit.patches.slice(0, PATCHES_PER_HIT).map(presentPatch) : [];
		const first = patches[0];
		views.push({
			caseId: hit.case.id,
			specimenLabel: hit.case.specimen_label?.trim() || 'Specimen not labelled',
			specialtyLabel: specialtyLabel(hit.case.specialty),
			accessioned: formatAccessioned(hit.case.accessioned_at),
			icd10: visibleIcd10(hit.case),
			authorName: hit.author.name,
			authorSynthetic: hit.author.is_synthetic,
			authorHref: pathologistSignedOutHref(hit.author.id),
			passage: mode === 'reports' ? presentPassage(hit.passage) : null,
			patches,
			openHref:
				mode === 'tissue' && first
					? caseHref(hit.case.id, { patch: first.id })
					: caseHref(hit.case.id),
			peekPatch: first?.peek ?? null
		});
	}
	return views;
}
