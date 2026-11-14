import { hasDirectoryFilter, type DirectoryQuery } from './query.js';

export type DirectoryScreen =
	| { kind: 'loading' }
	| { kind: 'error'; title: string; description: string; action: 'Retry' }
	| { kind: 'empty-filter'; title: string; description: string; action: 'Reset filters' }
	| { kind: 'empty'; title: string; description: string; action: 'Back to worklist' }
	| { kind: 'ready' };

export function directoryScreen(input: {
	loading: boolean;
	failed: boolean;
	itemCount: number;
	query: DirectoryQuery;
}): DirectoryScreen {
	if (input.itemCount === 0 && input.loading) return { kind: 'loading' };
	if (input.failed && input.itemCount === 0) {
		return {
			kind: 'error',
			title: 'Patients could not be loaded',
			description: 'Check the connection and try again.',
			action: 'Retry'
		};
	}
	if (input.itemCount > 0) return { kind: 'ready' };
	if (hasDirectoryFilter(input.query)) {
		return {
			kind: 'empty-filter',
			title: 'No patients match this filter',
			description: 'Clear the search or include single-case patients.',
			action: 'Reset filters'
		};
	}
	return {
		kind: 'empty',
		title: 'No patients have been ingested',
		description: 'The cohort has no patient records yet.',
		action: 'Back to worklist'
	};
}

export type PatientRecordScreen = 'loading' | 'not-found' | 'error' | 'ready';

export function patientRecordScreen(input: {
	loading: boolean;
	notFound: boolean;
	failed: boolean;
}): PatientRecordScreen {
	if (input.loading) return 'loading';
	if (input.notFound) return 'not-found';
	if (input.failed) return 'error';
	return 'ready';
}

export type PatientSearchScreen = 'timeline' | 'loading' | 'error' | 'empty' | 'results';

export function patientSearchScreen(input: {
	active: boolean;
	loading: boolean;
	failed: boolean;
	hitCount: number;
}): PatientSearchScreen {
	if (!input.active) return 'timeline';
	if (input.failed && input.hitCount === 0) return 'error';
	if (input.loading && input.hitCount === 0) return 'loading';
	if (input.hitCount === 0) return 'empty';
	return 'results';
}
