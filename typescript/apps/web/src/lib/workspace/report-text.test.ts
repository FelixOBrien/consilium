import { describe, expect, test } from 'bun:test';
import { formatZoom } from './viewport-url.js';
import {
	authorWorklistQuery,
	caseOpenQuery,
	formatSignOutDate,
	isTargetWord,
	phraseAfterSelect,
	phrasesMatch,
	presentReport,
	reportTextIntent,
	segmentReportText,
	visibleCaseIcd10,
	type SignedReport
} from './report-text.js';

function signedReport(overrides: Partial<SignedReport> = {}): SignedReport {
	return {
		id: 'case-1-r1',
		case_id: 'case-1',
		status: 'signed',
		body: 'Clinical History:\nCough.\n\nConclusion:\nAdenocarcinoma, NOS.',
		clinical_history: 'Cough for several weeks.',
		gross_description: 'A firm pale fragment.',
		microscopic_description: 'Glands in desmoplastic stroma.',
		conclusion: 'Adenocarcinoma, NOS.',
		additional_info: 'Levels were examined.',
		icd10: 'C50.9',
		signed_at: '2025-08-04T00:00:00.000Z',
		is_synthetic_author: true,
		author: {
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			is_synthetic: true,
			primary_specialty: 'breast'
		},
		...overrides
	};
}

describe('report sections', () => {
	test('keeps non-empty extracted sections in documented order and the full body', () => {
		const display = presentReport(signedReport());
		expect(display.kind).toBe('reported');
		expect(display.blocks.map((block) => block.id)).toEqual([
			'clinical_history',
			'gross_description',
			'microscopic_description',
			'conclusion',
			'additional_info',
			'icd10'
		]);
		expect(display.blocks.map((block) => block.label)).toEqual([
			'Clinical history',
			'Gross description',
			'Microscopic description',
			'Conclusion',
			'Additional information',
			'ICD-10'
		]);
		expect(display.bodyMode).toBe('alongside');
		expect(display.body).toContain('Adenocarcinoma, NOS.');
		expect(display.author).toEqual({
			id: 'path-okafor',
			name: 'Dr A. Okafor',
			synthetic: true
		});
		expect(display.signedAtLabel).toBe('4 Aug 2025');
		expect(display.synthetic).toBe(true);
	});

	test('drops empty sections and shows the body directly when no later heading matched', () => {
		const display = presentReport(
			signedReport({
				gross_description: '   ',
				microscopic_description: null,
				conclusion: '',
				additional_info: null,
				icd10: null,
				body: 'Unsectioned OCR text about glands.'
			})
		);
		expect(display.blocks.map((block) => block.id)).toEqual(['clinical_history']);
		expect(display.bodyMode).toBe('inline');
		expect(display.body).toBe('Unsectioned OCR text about glands.');
	});

	test('keeps ICD-10 when the body is shown directly', () => {
		const display = presentReport(
			signedReport({
				gross_description: null,
				microscopic_description: null,
				conclusion: null,
				additional_info: null
			})
		);
		expect(display.blocks.map((block) => block.id)).toEqual(['clinical_history', 'icd10']);
		expect(display.bodyMode).toBe('inline');
	});

	test('an open case shows clinical history only', () => {
		const display = presentReport({
			case_id: 'case-open',
			status: 'none',
			clinical_history: 'Imaging prompted the request.'
		});
		expect(display.kind).toBe('unreported');
		expect(display.blocks).toEqual([
			{
				id: 'clinical_history',
				label: 'Clinical history',
				text: 'Imaging prompted the request.'
			}
		]);
		expect(display.body).toBeNull();
		expect(display.bodyMode).toBe('absent');
		expect(display.author).toBeNull();
		expect(display.synthetic).toBe(false);
		expect(JSON.stringify(display).includes('conclusion')).toBe(false);
		expect(JSON.stringify(display).includes('microscopic')).toBe(false);
	});

	test('an open case with no history is the notice alone', () => {
		const display = presentReport({
			case_id: 'case-open',
			status: 'none',
			clinical_history: '  '
		});
		expect(display.blocks).toEqual([]);
		expect(display.body).toBeNull();
	});

	test('a draft report is still readable and marked synthetic', () => {
		const display = presentReport(
			signedReport({ status: 'draft', signed_at: null, is_synthetic_author: true })
		);
		expect(display.kind).toBe('reported');
		expect(display.signedAtLabel).toBeNull();
		expect(display.synthetic).toBe(true);
	});
});

describe('eligible report words', () => {
	test('preserves every character and marks only informative words', () => {
		const text = 'The carcinoma, NOS.\nWell-differentiated glands.';
		const spans = segmentReportText(text);
		expect(spans.map((span) => span.text).join('')).toBe(text);
		expect(spans.filter((span) => span.kind === 'word').map((span) => span.text)).toEqual([
			'carcinoma',
			'NOS',
			'Well-differentiated',
			'glands'
		]);
	});

	test('stop words, punctuation and bare numbers are not targets', () => {
		expect(isTargetWord('the')).toBe(false);
		expect(isTargetWord('and')).toBe(false);
		expect(isTargetWord('of')).toBe(false);
		expect(isTargetWord("don't")).toBe(false);
		expect(isTargetWord('a')).toBe(false);
		expect(isTargetWord(',')).toBe(false);
		expect(isTargetWord('12')).toBe(false);
		expect(isTargetWord('50.9')).toBe(false);
		expect(isTargetWord('C50.9')).toBe(true);
		expect(isTargetWord('T2a')).toBe(true);
		expect(isTargetWord('glands')).toBe(true);
	});

	test('selecting the active word clears it and another word replaces it', () => {
		expect(phraseAfterSelect(null, 'glands')).toBe('glands');
		expect(phraseAfterSelect('glands', 'Glands')).toBeNull();
		expect(phraseAfterSelect('glands', 'stroma')).toBe('stroma');
		expect(phrasesMatch('Carcinoma', 'carcinoma')).toBe(true);
		expect(phrasesMatch(null, 'carcinoma')).toBe(false);
	});
});

describe('report actions', () => {
	test('author link filters the worklist to that pathologist’s signed-out cases', () => {
		expect(authorWorklistQuery('path-okafor')).toBe(
			'assigned_to=path-okafor&status=signed_out&view=all'
		);
	});

	test('opening a patch centres on it and keeps the patch id', () => {
		const query = new URLSearchParams(
			caseOpenQuery({ id: '42', slide_id: 'case-1-s1', x: 0, y: 512, size: 512 })
		);
		expect(query.get('patch')).toBe('42');
		expect(query.get('slide')).toBe('case-1-s1');
		expect(query.get('x')).toBe('256');
		expect(query.get('y')).toBe('768');
		expect(query.get('zoom')).toBe(formatZoom(320 / 512));
	});

	test('a patch without a size still names the patch and slide', () => {
		const query = new URLSearchParams(caseOpenQuery({ id: '7', slide_id: 'slide-a', x: 1, y: 2 }));
		expect(query.get('patch')).toBe('7');
		expect(query.get('slide')).toBe('slide-a');
		expect(query.has('zoom')).toBe(false);
		expect(caseOpenQuery(null)).toBe('');
	});

	test('report text for evidence search collapses whitespace and drops blanks', () => {
		expect(reportTextIntent('  glands \n in   stroma ')).toEqual({
			kind: 'report_text',
			text: 'glands in stroma'
		});
		expect(reportTextIntent('   ')).toBeNull();
	});

	test('ICD-10 is visible only for a signed-out case', () => {
		expect(visibleCaseIcd10({ status: 'signed_out', icd10: ' C50.9 ' })).toBe('C50.9');
		expect(visibleCaseIcd10({ status: 'open', icd10: 'C50.9' })).toBeNull();
		expect(visibleCaseIcd10({ status: 'signed_out', icd10: '  ' })).toBeNull();
	});

	test('sign-out dates use a calendar day', () => {
		expect(formatSignOutDate('2026-02-16T18:30:00.000Z')).toBe('16 Feb 2026');
		expect(formatSignOutDate(null)).toBeNull();
		expect(formatSignOutDate('not-a-date')).toBeNull();
	});
});
