<script lang="ts">
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	import Typography from './Typography.svelte';

	let {
		icon = 'search',
		title,
		description,
		action,
		onaction
	}: {
		icon?: 'search' | 'database' | 'warning' | 'annotation';
		title: string;
		description: string;
		action?: string;
		onaction?: () => void;
	} = $props();
</script>

<div class="empty-state">
	<span class="empty-icon"><Icon name={icon} size="lg" /></span>
	<div class="empty-copy">
		<Typography as="h3" style="subsection">{title}</Typography>
		<Typography tone="secondary">{description}</Typography>
	</div>
	{#if action}
		<Button variant="secondary" onclick={onaction}>{action}</Button>
	{/if}
</div>

<style>
	.empty-state {
		display: grid;
		place-items: center;
		gap: var(--space-4);
		padding: var(--space-12) var(--space-6);
		text-align: center;
	}
	.empty-icon {
		display: grid;
		place-items: center;
		width: var(--empty-icon);
		height: var(--empty-icon);
		border-radius: var(--radius-xl);
		background: var(--color-action-soft);
		color: var(--color-action);
	}
	.empty-copy {
		display: grid;
		gap: var(--space-2);
		max-width: var(--measure-sm);
	}
</style>
