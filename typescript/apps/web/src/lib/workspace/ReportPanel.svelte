<script lang="ts">
	import ReportView from './ReportView.svelte';
	import { loadCaseReport, type ReportLoad } from './report-load.js';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
	let load = $state<ReportLoad>({ phase: 'loading' });
	let attempt = $state(0);

	$effect(() => {
		const caseId = caseState.caseId;
		const current = attempt;
		if (!caseId) {
			load = { phase: 'loading' };
			return;
		}
		let cancelled = false;
		load = { phase: 'loading' };
		void loadCaseReport(caseId).then((result) => {
			if (cancelled) return;
			void current;
			load = result;
		});
		return () => {
			cancelled = true;
		};
	});

	const activePhrase = $derived(caseState.heatmapPhraseRequest?.phrase ?? null);

	function onPhrase(phrase: string | null) {
		caseState.requestHeatmapPhrase(phrase);
	}

	function onFindSimilar(text: string) {
		caseState.triggerEvidenceSearch({ kind: 'report_text', text });
	}
</script>

<div class="report-panel">
	<ReportView
		{load}
		{activePhrase}
		{onPhrase}
		{onFindSimilar}
		onretry={() => {
			attempt += 1;
		}}
	/>
</div>

<style>
	.report-panel {
		min-width: 0;
	}
</style>
