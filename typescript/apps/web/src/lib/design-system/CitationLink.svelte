<script lang="ts">
	import type { Snippet } from 'svelte';
	let { children, onclick }: { children: Snippet; onclick?: () => void } = $props();
</script>

<button {onclick}>{@render children()}</button>

<style>
	button {
		padding: 0;
		border: 0;
		border-bottom: var(--border-width) solid currentColor;
		background: transparent;
		color: var(--color-action);
		font: inherit;
		cursor: pointer;
	}
</style>
