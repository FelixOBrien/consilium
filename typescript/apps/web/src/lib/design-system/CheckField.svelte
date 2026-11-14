<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Checkbox } from '#lib/components/ui/checkbox/index.js';
	let {
		checked = $bindable(false),
		children
	}: {
		checked?: boolean;
		children: Snippet;
	} = $props();
</script>

<label class="check-field">
	<Checkbox bind:checked />
	{@render children()}
</label>

<style>
	.check-field {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		cursor: pointer;
	}
</style>
