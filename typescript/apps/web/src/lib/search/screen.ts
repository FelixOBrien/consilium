export type SearchScreen = 'redirect' | 'loading' | 'error' | 'empty' | 'results';

export function searchScreen(input: {
	hasQuery: boolean;
	searching: boolean;
	failed: boolean;
	count: number;
}): SearchScreen {
	if (!input.hasQuery) return 'redirect';
	if (input.failed && !input.searching && input.count === 0) return 'error';
	if (input.searching && input.count === 0) return 'loading';
	if (!input.searching && !input.failed && input.count === 0) return 'empty';
	return 'results';
}
