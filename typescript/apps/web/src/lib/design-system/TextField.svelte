<script lang="ts">
	import Icon from './Icon.svelte';
	import { Input } from '#lib/components/ui/input/index.js';

	let {
		value = $bindable(''),
		placeholder = '',
		label,
		icon = 'search',
		type = 'text',
		compact = false,
		name,
		disabled = false
	}: {
		value?: string;
		placeholder?: string;
		label?: string;
		icon?: 'search' | 'evidence' | 'report' | 'spark' | 'annotation' | 'heatmap' | 'database';
		type?: 'text' | 'search';
		compact?: boolean;
		name?: string;
		disabled?: boolean;
	} = $props();
</script>

<label class:compact class="field">
	{#if label}<span class="field-label">{label}</span>{/if}
	<span class="input-wrap">
		<Icon name={icon} size="sm" />
		<Input class="consilium-input" bind:value {placeholder} {type} {name} {disabled} />
	</span>
</label>

<style>
	.field {
		display: grid;
		gap: var(--space-2);
		min-width: 0;
	}
	.field-label {
		font: var(--font-label-sm);
		color: var(--color-text-secondary);
	}
	.input-wrap {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--control-lg);
		padding: 0 var(--space-4);
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text-muted);
		box-shadow: var(--shadow-inset);
	}
	.input-wrap:focus-within {
		border-color: var(--color-action);
		box-shadow: var(--shadow-focus);
	}
	.input-wrap :global(.consilium-input) {
		width: 100%;
		min-width: 0;
		height: auto;
		padding: 0;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--color-text);
		font: var(--font-body);
		box-shadow: none;
	}
	.input-wrap :global(.consilium-input::placeholder) {
		color: var(--color-text-muted);
	}
	.compact .input-wrap {
		min-height: var(--control-md);
		padding: 0 var(--space-3);
	}
</style>
