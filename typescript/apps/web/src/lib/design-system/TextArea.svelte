<script lang="ts">
	import Typography from './Typography.svelte';
	import { Textarea } from '#lib/components/ui/textarea/index.js';
	let {
		value = $bindable(''),
		label,
		rows = 3
	}: {
		value?: string;
		label: string;
		rows?: number;
	} = $props();
</script>

<label class="text-area">
	<Typography as="span" style="label" tone="secondary">{label}</Typography>
	<Textarea class="consilium-textarea" bind:value {rows} />
</label>

<style>
	.text-area {
		display: grid;
		gap: var(--space-2);
	}
	.text-area :global(.consilium-textarea) {
		resize: vertical;
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: var(--font-body);
		outline: 0;
	}
	.text-area :global(.consilium-textarea:focus) {
		border-color: var(--color-action);
		box-shadow: var(--shadow-focus);
	}
</style>
