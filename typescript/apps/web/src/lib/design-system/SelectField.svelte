<script lang="ts">
	import Icon from './Icon.svelte';

	let {
		label,
		value = $bindable(''),
		options,
		compact = false
	}: {
		label?: string;
		value?: string;
		options: string[];
		compact?: boolean;
	} = $props();
</script>

<label class:compact class="field">
	{#if label}<span class="field-label">{label}</span>{/if}
	<span class="select-wrap">
		<select bind:value>
			{#each options as option (option)}
				<option value={option}>{option}</option>
			{/each}
		</select>
		<Icon name="chevron-down" size="sm" />
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
	.select-wrap {
		position: relative;
		display: flex;
		align-items: center;
		min-height: var(--control-lg);
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		box-shadow: var(--shadow-xs);
	}
	.select-wrap:focus-within {
		border-color: var(--color-action);
		box-shadow: var(--shadow-focus);
	}
	select {
		width: 100%;
		min-height: inherit;
		padding: 0 var(--space-10) 0 var(--space-4);
		appearance: none;
		border: 0;
		outline: 0;
		background: transparent;
		color: var(--color-text);
		font: var(--font-label);
		cursor: pointer;
	}
	.select-wrap :global(svg) {
		position: absolute;
		right: var(--space-3);
		pointer-events: none;
		color: var(--color-text-muted);
	}
	.compact .select-wrap {
		min-height: var(--control-md);
	}
	.compact select {
		padding-left: var(--space-3);
		font: var(--font-label-sm);
	}
</style>
