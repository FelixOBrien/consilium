/**
 * Safe markdown for consult answers.
 * The model is untrusted. This tokenizer returns an AST that the panel renders
 * as Svelte elements. It never produces HTML and must not be passed to `{@html}`.
 */

export type MarkdownInline =
	| { type: 'text'; text: string }
	| { type: 'strong'; children: MarkdownInline[] }
	| { type: 'em'; children: MarkdownInline[] }
	| { type: 'code'; text: string }
	| { type: 'citation'; caseId: string };

export type MarkdownBlock =
	| { type: 'paragraph'; children: MarkdownInline[] }
	| { type: 'heading'; level: 1 | 2 | 3; children: MarkdownInline[] }
	| { type: 'list'; ordered: boolean; items: MarkdownInline[][] }
	| { type: 'quote'; children: MarkdownInline[] }
	| { type: 'code'; text: string };

const CASE_MARKER = /^\[case:([^\s\]]+)\]/;

export function parseMarkdown(source: string): MarkdownBlock[] {
	const lines = source.replaceAll('\r\n', '\n').split('\n');
	const blocks: MarkdownBlock[] = [];
	let index = 0;
	while (index < lines.length) {
		const line = lines[index] ?? '';
		if (line.trim() === '') {
			index += 1;
			continue;
		}
		if (line.startsWith('```')) {
			const body: string[] = [];
			index += 1;
			while (index < lines.length && !(lines[index] ?? '').startsWith('```')) {
				body.push(lines[index] ?? '');
				index += 1;
			}
			if (index < lines.length) index += 1;
			blocks.push({ type: 'code', text: body.join('\n') });
			continue;
		}
		const heading = /^(#{1,3})\s+(.*)$/.exec(line);
		if (heading) {
			const marks = heading[1] ?? '#';
			const level = marks.length as 1 | 2 | 3;
			blocks.push({ type: 'heading', level, children: parseInlines(heading[2] ?? '') });
			index += 1;
			continue;
		}
		if (isQuote(line)) {
			const quote: string[] = [];
			while (index < lines.length && isQuote(lines[index] ?? '')) {
				quote.push((lines[index] ?? '').replace(/^>\s?/, ''));
				index += 1;
			}
			blocks.push({ type: 'quote', children: parseInlines(quote.join(' ')) });
			continue;
		}
		if (isListLine(line)) {
			const ordered = /^\s*\d+\.\s+/.test(line);
			const items: MarkdownInline[][] = [];
			while (index < lines.length && isListLine(lines[index] ?? '')) {
				const current = lines[index] ?? '';
				if (/^\s*\d+\.\s+/.test(current) !== ordered) break;
				items.push(parseInlines(current.replace(/^\s*(?:[-*]|\d+\.)\s+/, '')));
				index += 1;
			}
			blocks.push({ type: 'list', ordered, items });
			continue;
		}
		const paragraph: string[] = [];
		while (
			index < lines.length &&
			(lines[index] ?? '').trim() !== '' &&
			!startsBlock(lines[index] ?? '')
		) {
			paragraph.push(lines[index] ?? '');
			index += 1;
		}
		blocks.push({ type: 'paragraph', children: parseInlines(paragraph.join(' ')) });
	}
	return blocks;
}

export function parseInlines(input: string): MarkdownInline[] {
	const nodes: MarkdownInline[] = [];
	let index = 0;
	while (index < input.length) {
		if (input.startsWith('**', index)) {
			const end = input.indexOf('**', index + 2);
			if (end !== -1) {
				nodes.push({ type: 'strong', children: parseInlines(input.slice(index + 2, end)) });
				index = end + 2;
				continue;
			}
		}
		if (input[index] === '`') {
			const end = input.indexOf('`', index + 1);
			if (end !== -1) {
				nodes.push({ type: 'code', text: input.slice(index + 1, end) });
				index = end + 1;
				continue;
			}
		}
		const marker = CASE_MARKER.exec(input.slice(index));
		if (marker?.[1]) {
			nodes.push({ type: 'citation', caseId: marker[1] });
			index += marker[0].length;
			continue;
		}
		if (input[index] === '*' && input[index + 1] !== '*') {
			const end = input.indexOf('*', index + 1);
			if (end !== -1) {
				nodes.push({ type: 'em', children: parseInlines(input.slice(index + 1, end)) });
				index = end + 1;
				continue;
			}
		}
		let next = index + 1;
		while (next < input.length && !isInlineBoundary(input, next)) next += 1;
		nodes.push({ type: 'text', text: input.slice(index, next) });
		index = next;
	}
	return mergeText(nodes);
}

function mergeText(nodes: MarkdownInline[]): MarkdownInline[] {
	const merged: MarkdownInline[] = [];
	for (const node of nodes) {
		const previous = merged.at(-1);
		if (node.type === 'text' && previous?.type === 'text') {
			previous.text += node.text;
			continue;
		}
		if (node.type === 'text' && node.text === '') continue;
		merged.push(node);
	}
	return merged;
}

function isInlineBoundary(input: string, index: number): boolean {
	if (input.startsWith('**', index) || input.startsWith('[case:', index)) return true;
	const char = input[index];
	return char === '*' || char === '`';
}

function startsBlock(line: string): boolean {
	return line.startsWith('```') || /^(#{1,3})\s+/.test(line) || isQuote(line) || isListLine(line);
}

function isQuote(line: string): boolean {
	return line.startsWith('>');
}

function isListLine(line: string): boolean {
	return /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line);
}
