import { describe, expect, test } from 'bun:test';
import { parseInlines, parseMarkdown } from './consult-markdown.js';

describe('consult markdown', () => {
	test('turns [case:id] markers into citation nodes and leaves surrounding text', () => {
		expect(parseInlines('See [case:breast-TCGA-A2-0001] and [case:thorax-TCGA-B1-0004].')).toEqual([
			{ type: 'text', text: 'See ' },
			{ type: 'citation', caseId: 'breast-TCGA-A2-0001' },
			{ type: 'text', text: ' and ' },
			{ type: 'citation', caseId: 'thorax-TCGA-B1-0004' },
			{ type: 'text', text: '.' }
		]);
	});

	test('keeps an unfinished case marker as text so a stream can complete it', () => {
		expect(parseInlines('See [case:breast-TCGA-A2-0001')).toEqual([
			{ type: 'text', text: 'See [case:breast-TCGA-A2-0001' }
		]);
	});

	test('renders emphasis around a citation and does not treat model HTML as markup', () => {
		expect(
			parseMarkdown(
				'**Similar cases** include [case:breast-TCGA-A2-0001].\n\n<script>alert(1)</script>'
			)
		).toEqual([
			{
				type: 'paragraph',
				children: [
					{ type: 'strong', children: [{ type: 'text', text: 'Similar cases' }] },
					{ type: 'text', text: ' include ' },
					{ type: 'citation', caseId: 'breast-TCGA-A2-0001' },
					{ type: 'text', text: '.' }
				]
			},
			{
				type: 'paragraph',
				children: [{ type: 'text', text: '<script>alert(1)</script>' }]
			}
		]);
	});

	test('does not turn markdown links or code into citations or hrefs', () => {
		const blocks = parseMarkdown(
			'A [click](javascript:alert(1)) link.\n\nUse `[case:breast-TCGA-A2-0001]` literally.\n\n```\n[case:hidden]\n<img src=x onerror=alert(1)>\n```'
		);
		expect(blocks).toEqual([
			{
				type: 'paragraph',
				children: [{ type: 'text', text: 'A [click](javascript:alert(1)) link.' }]
			},
			{
				type: 'paragraph',
				children: [
					{ type: 'text', text: 'Use ' },
					{ type: 'code', text: '[case:breast-TCGA-A2-0001]' },
					{ type: 'text', text: ' literally.' }
				]
			},
			{
				type: 'code',
				text: '[case:hidden]\n<img src=x onerror=alert(1)>'
			}
		]);
		expect(JSON.stringify(blocks).includes('"href"')).toBe(false);
	});

	test('parses lists, headings, and emphasis', () => {
		expect(
			parseMarkdown('## What was retrieved\n\n- Glands [case:breast-TCGA-A2-0001]\n- *Stroma*\n')
		).toEqual([
			{
				type: 'heading',
				level: 2,
				children: [{ type: 'text', text: 'What was retrieved' }]
			},
			{
				type: 'list',
				ordered: false,
				items: [
					[
						{ type: 'text', text: 'Glands ' },
						{ type: 'citation', caseId: 'breast-TCGA-A2-0001' }
					],
					[{ type: 'em', children: [{ type: 'text', text: 'Stroma' }] }]
				]
			}
		]);
	});
});
