<script lang="ts">
	let {
		items,
		value = $bindable(),
		onchange
	}: {
		items: { label: string; value: string; count?: number | string }[];
		value: string;
		onchange?: (value: string) => void;
	} = $props();
</script>

<div class="segmented" role="tablist">
	{#each items as item (item.value)}
		<button
			class:active={item.value === value}
			role="tab"
			aria-selected={item.value === value}
			onclick={() => {
				value = item.value;
				onchange?.(item.value);
			}}
		>
			{item.label}
			{#if item.count !== undefined}<span>{item.count}</span>{/if}
		</button>
	{/each}
</div>

<style>
	.segmented {
		display: inline-flex;
		gap: var(--space-1);
		padding: var(--space-1);
		border-radius: var(--radius-lg);
		background: var(--color-surface-subtle);
		border: var(--border-width) solid var(--color-border);
	}
	button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--control-sm);
		padding: 0 var(--space-4);
		border: 0;
		border-radius: var(--radius-md);
		background: transparent;
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
		cursor: pointer;
	}
	button:focus-visible {
		outline: var(--focus-ring);
		outline-offset: var(--focus-offset);
	}
	button.active {
		background: var(--color-surface);
		color: var(--color-text);
		box-shadow: var(--shadow-sm);
	}
	button span {
		color: var(--color-text-muted);
		font: var(--font-label-xs);
	}
</style>
