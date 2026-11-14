import { formatLevel0, formatZoom } from './viewport-url.js';

/**
 * Report text for S-03 / F-04 / F-06.
 * Eligible targets are informative words: not stop words, not punctuation,
 * and long enough to be a term. The report string itself is never rewritten.
 */

type Schemas = import('#lib/api/schema.js').components['schemas'];

export type CaseReport = Schemas['Report'] | Schemas['ReportNotReported'];
export type SignedReport = Schemas['Report'];
export type CaseDetail = Schemas['CaseDetail'];

export type ReportSpan = { kind: 'text'; text: string } | { kind: 'word'; text: string };

export type ReportBlockId =
	| 'clinical_history'
	| 'gross_description'
	| 'microscopic_description'
	| 'conclusion'
	| 'additional_info'
	| 'icd10';

export type ReportBlock = {
	id: ReportBlockId;
	label: string;
	text: string;
};

export type ReportBodyMode = 'inline' | 'alongside' | 'absent';

export type ReportDisplay = {
	kind: 'reported' | 'unreported';
	blocks: ReportBlock[];
	body: string | null;
	bodyMode: ReportBodyMode;
	author: { id: string; name: string; synthetic: boolean } | null;
	signedAtLabel: string | null;
	synthetic: boolean;
};

export type PeekPatch = {
	id: string;
	slide_id: string;
	x: number;
	y: number;
	size?: number;
};

/** Snowball English stop words, plus contraction cores (`don't` → `dont`). */
const STOP_WORDS = new Set([
	'a',
	'about',
	'above',
	'after',
	'again',
	'against',
	'all',
	'am',
	'an',
	'and',
	'any',
	'are',
	'aren',
	'arent',
	'as',
	'at',
	'be',
	'because',
	'been',
	'before',
	'being',
	'below',
	'between',
	'both',
	'but',
	'by',
	'can',
	'cant',
	'could',
	'couldn',
	'couldnt',
	'did',
	'didn',
	'didnt',
	'do',
	'does',
	'doesn',
	'doesnt',
	'doing',
	'don',
	'dont',
	'down',
	'during',
	'each',
	'few',
	'for',
	'from',
	'further',
	'had',
	'hadn',
	'hadnt',
	'has',
	'hasn',
	'hasnt',
	'have',
	'haven',
	'havent',
	'having',
	'he',
	'her',
	'here',
	'hers',
	'herself',
	'him',
	'himself',
	'his',
	'how',
	'i',
	'if',
	'in',
	'into',
	'is',
	'isn',
	'isnt',
	'it',
	'its',
	'itself',
	'just',
	'me',
	'more',
	'most',
	'mustn',
	'mustnt',
	'my',
	'myself',
	'no',
	'nor',
	'not',
	'now',
	'of',
	'off',
	'on',
	'once',
	'only',
	'or',
	'other',
	'our',
	'ours',
	'ourselves',
	'out',
	'over',
	'own',
	's',
	'same',
	'she',
	'should',
	'shouldn',
	'shouldnt',
	'so',
	'some',
	'such',
	't',
	'than',
	'that',
	'the',
	'their',
	'theirs',
	'them',
	'themselves',
	'then',
	'there',
	'these',
	'they',
	'this',
	'those',
	'through',
	'to',
	'too',
	'under',
	'until',
	'up',
	'very',
	'was',
	'wasn',
	'wasnt',
	'we',
	'were',
	'weren',
	'werent',
	'what',
	'when',
	'where',
	'which',
	'while',
	'who',
	'whom',
	'why',
	'will',
	'with',
	'won',
	'wont',
	'would',
	'wouldn',
	'wouldnt',
	'you',
	'your',
	'yours',
	'yourself',
	'yourselves'
]);

const TOKEN = /[A-Za-z0-9]+(?:['’.-][A-Za-z0-9]+)*/g;

const TEXT_SECTIONS = [
	{
		key: 'clinical_history',
		label: 'Clinical history',
		postHistory: false
	},
	{
		key: 'gross_description',
		label: 'Gross description',
		postHistory: true
	},
	{
		key: 'microscopic_description',
		label: 'Microscopic description',
		postHistory: true
	},
	{
		key: 'conclusion',
		label: 'Conclusion',
		postHistory: true
	},
	{
		key: 'additional_info',
		label: 'Additional information',
		postHistory: true
	}
] as const;

export function isReported(report: CaseReport): report is SignedReport {
	return report.status === 'signed' || report.status === 'draft';
}

export function nonempty(value: string | null | undefined): string | null {
	const trimmed = value?.trim() ?? '';
	return trimmed || null;
}

function wordCore(token: string): string {
	return token.toLocaleLowerCase('en').replace(/[^a-z0-9]/g, '');
}

/** True when a token can be mapped onto the open slide. */
export function isTargetWord(token: string): boolean {
	const core = wordCore(token);
	if (core.length < 3) return false;
	if (!/[a-z]/.test(core)) return false;
	return !STOP_WORDS.has(core);
}

export function segmentReportText(text: string): ReportSpan[] {
	const spans: ReportSpan[] = [];
	let last = 0;
	for (const match of text.matchAll(TOKEN)) {
		const index = match.index ?? 0;
		if (index > last) pushText(spans, text.slice(last, index));
		const token = match[0];
		if (isTargetWord(token)) spans.push({ kind: 'word', text: token });
		else pushText(spans, token);
		last = index + token.length;
	}
	if (last < text.length) pushText(spans, text.slice(last));
	return spans;
}

function pushText(spans: ReportSpan[], text: string): void {
	if (!text) return;
	const last = spans.at(-1);
	if (last?.kind === 'text') last.text += text;
	else spans.push({ kind: 'text', text });
}

export function phrasesMatch(active: string | null | undefined, word: string): boolean {
	if (!active) return false;
	return active.toLocaleLowerCase('en') === word.toLocaleLowerCase('en');
}

/** Selecting the active word clears it. Any other eligible word replaces it. */
export function phraseAfterSelect(active: string | null | undefined, word: string): string | null {
	if (phrasesMatch(active, word)) return null;
	return word;
}

export function formatSignOutDate(iso: string | null | undefined): string | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return null;
	return new Intl.DateTimeFormat('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric',
		timeZone: 'UTC'
	}).format(date);
}

/**
 * Worklist of the author's signed-out cases.
 * `/?assigned_to=<id>&status=signed_out&view=all`
 */
export function authorWorklistQuery(authorId: string): string {
	return new URLSearchParams({
		assigned_to: authorId,
		status: 'signed_out',
		view: 'all'
	}).toString();
}

/**
 * Query that opens a case on a patch. With a known size the centre and zoom
 * are included so the viewer frames that patch; `patch` is always set so the
 * patch stays marked when the record is loaded.
 */
export function caseOpenQuery(patch: PeekPatch | null | undefined): string {
	if (!patch) return '';
	const params = new URLSearchParams();
	if (patch.id) params.set('patch', patch.id);
	if (patch.slide_id) params.set('slide', patch.slide_id);
	if (
		patch.size != null &&
		patch.size > 0 &&
		Number.isFinite(patch.x) &&
		Number.isFinite(patch.y)
	) {
		params.set('x', formatLevel0(patch.x + patch.size / 2));
		params.set('y', formatLevel0(patch.y + patch.size / 2));
		const zoom = formatZoom(320 / patch.size);
		if (zoom) params.set('zoom', zoom);
	}
	return params.toString();
}

/** Report-text handoff for the evidence panel. Empty selections are dropped. */
export function reportTextIntent(text: string): { kind: 'report_text'; text: string } | null {
	const trimmed = text.replace(/\s+/g, ' ').trim();
	if (!trimmed) return null;
	return { kind: 'report_text', text: trimmed };
}

export function readReportSelection(root: HTMLElement | null): string | null {
	if (!root || typeof window === 'undefined') return null;
	const selection = window.getSelection();
	if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
	const range = selection.getRangeAt(0);
	if (!root.contains(range.commonAncestorContainer)) return null;
	return reportTextIntent(selection.toString())?.text ?? null;
}

/** ICD-10 is shown only after sign-out. Open cases never surface a code. */
export function visibleCaseIcd10(detail: Pick<CaseDetail, 'status' | 'icd10'>): string | null {
	if (detail.status !== 'signed_out') return null;
	return nonempty(detail.icd10);
}

export function presentReport(report: CaseReport): ReportDisplay {
	if (!isReported(report)) {
		const history = nonempty(report.clinical_history);
		return {
			kind: 'unreported',
			blocks: history ? [{ id: 'clinical_history', label: 'Clinical history', text: history }] : [],
			body: null,
			bodyMode: 'absent',
			author: null,
			signedAtLabel: null,
			synthetic: false
		};
	}

	const blocks: ReportBlock[] = [];
	let postHistory = false;
	for (const section of TEXT_SECTIONS) {
		const text = nonempty(report[section.key]);
		if (!text) continue;
		if (section.postHistory) postHistory = true;
		blocks.push({ id: section.key, label: section.label, text });
	}
	const icd10 = nonempty(report.icd10);
	if (icd10) blocks.push({ id: 'icd10', label: 'ICD-10', text: icd10 });

	const body = nonempty(report.body);
	const bodyMode: ReportBodyMode = !body ? 'absent' : postHistory ? 'alongside' : 'inline';
	return {
		kind: 'reported',
		blocks,
		body,
		bodyMode,
		author: {
			id: report.author.id,
			name: report.author.name,
			synthetic: report.is_synthetic_author || report.author.is_synthetic
		},
		signedAtLabel: formatSignOutDate(report.signed_at),
		synthetic: report.is_synthetic_author || report.author.is_synthetic
	};
}
