<script lang="ts">
	import { highlightSegments } from './present.js';

	let {
		text,
		highlights
	}: {
		text: string;
		highlights: readonly (readonly [number, number])[];
	} = $props();

	const segments = $derived(highlightSegments(text, highlights));
</script>

<span class="passage-text">
	{#each segments as segment, index (index)}
		{#if segment.mark}<mark>{segment.text}</mark>{:else}{segment.text}{/if}
	{/each}
</span>

<style>
	mark {
		padding: 0 var(--space-1);
		border-radius: var(--radius-xs);
		background: var(--color-warning-soft);
		color: inherit;
	}
</style>
