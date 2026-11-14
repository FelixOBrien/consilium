/**
 * Test hooks for the report-word overlay while the report panel (SKO-274) is on another branch.
 * Neither hook adds a phrase field to the product UI.
 * `?word=` selects once. `?debug_overlay=1` shows a single sample-word button only while idle.
 * `window.__consiliumSelectReportWord` publishes or clears a word for a browser check. // pragma: allowlist secret
 */

export type ReportWordSelect = (phrase: string | null) => void;

export type HeatmapDevHook = {
	word: string | null;
	debugOverlay: boolean;
};

type HookHost = typeof globalThis & {
	__consiliumSelectReportWord?: ReportWordSelect; // pragma: allowlist secret
};

export const DEBUG_SAMPLE_WORD = 'stroma';

export function readHeatmapDevHook(search: string): HeatmapDevHook {
	const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
	const word = params.get('word')?.trim() ?? '';
	return {
		word: word || null,
		debugOverlay: params.get('debug_overlay') === '1'
	};
}

export function installReportWordHook(select: ReportWordSelect): () => void {
	const host = globalThis as HookHost;
	const wrapped: ReportWordSelect = (phrase) => {
		const trimmed = phrase?.trim() ?? '';
		select(trimmed ? trimmed : null);
	};
	host.__consiliumSelectReportWord = wrapped; // pragma: allowlist secret
	return () => {
		if (host.__consiliumSelectReportWord === wrapped) delete host.__consiliumSelectReportWord; // pragma: allowlist secret
	};
}
