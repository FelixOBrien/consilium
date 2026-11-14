import type { WorklistQuery } from './query.js';
import { hasWorklistFilters } from './query.js';

export type WorklistScreen =
	| { kind: 'loading' }
	| {
			kind: 'error';
			title: string;
			description: string;
			action: 'Retry';
	  }
	| {
			kind: 'no-data';
			title: string;
			description: string;
			action: 'Open ingestion';
	  }
	| {
			kind: 'empty-queue';
			title: string;
			description: string;
			action: 'View all cases';
	  }
	| {
			kind: 'empty-filter';
			title: string;
			description: string;
			action: 'Clear filters';
	  }
	| { kind: 'ready' };

export function worklistScreen(input: {
	loading: boolean;
	failed: boolean;
	itemCount: number;
	query: WorklistQuery;
	/** `null` while the unfiltered corpus size is still unknown. */
	corpusEmpty: boolean | null;
	actingName: string | null;
}): WorklistScreen {
	if (input.itemCount === 0 && (input.loading || (input.corpusEmpty === null && !input.failed))) {
		return { kind: 'loading' };
	}
	if (input.failed && input.itemCount === 0) {
		return {
			kind: 'error',
			title: 'The worklist could not be loaded',
			description: 'Your filters have been kept. Check the connection and try again.',
			action: 'Retry'
		};
	}
	if (input.itemCount > 0) return { kind: 'ready' };
	if (input.corpusEmpty) {
		return {
			kind: 'no-data',
			title: 'No cases have been ingested',
			description: 'The corpus is empty. Load slides and reports, then return to the worklist.',
			action: 'Open ingestion'
		};
	}
	if (hasWorklistFilters(input.query)) {
		return {
			kind: 'empty-filter',
			title: 'No cases match these filters',
			description:
				'Try a broader specialty, status, pathologist or ICD-10 prefix, or clear the filters.',
			action: 'Clear filters'
		};
	}
	if (input.query.view === 'mine') {
		const name = input.actingName?.trim() || 'This pathologist';
		return {
			kind: 'empty-queue',
			title: 'No open cases assigned to you',
			description: `${name} has no assigned cases. Switch to All cases to browse the corpus.`,
			action: 'View all cases'
		};
	}
	return {
		kind: 'no-data',
		title: 'No cases have been ingested',
		description: 'The corpus is empty. Load slides and reports, then return to the worklist.',
		action: 'Open ingestion'
	};
}
