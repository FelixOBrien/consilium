<script lang="ts">
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret
</script>

<!-- Phrase heatmap controls are filled in by the heatmap issue. The mount stays here. -->
<div class="heatmap-controls" data-phrase={caseState.heatmapPhraseRequest?.phrase ?? ''}></div>

<style>
	.heatmap-controls {
		position: absolute;
		z-index: 5;
		top: 0;
		right: 0;
		left: 0;
		pointer-events: none;
	}
	.heatmap-controls:empty {
		display: none;
	}
</style>
