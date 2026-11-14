<script lang="ts">
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	import Typography from './Typography.svelte';
	let {
		tone = 'info',
		title,
		description,
		action,
		onaction
	}: {
		tone?: 'info' | 'warning' | 'danger' | 'success';
		title: string;
		description?: string;
		action?: string;
		onaction?: () => void;
	} = $props();
</script>

<div class="state-message {tone}">
	<Icon name={tone === 'danger' || tone === 'warning' ? 'warning' : 'activity'} />
	<div>
		<Typography style="label">{title}</Typography>
		{#if description}<Typography style="small" tone="secondary">{description}</Typography>{/if}
	</div>
	{#if action}<Button size="sm" variant="secondary" onclick={onaction}>{action}</Button>{/if}
</div>

<style>
	.state-message {
		display: grid;
		grid-template-columns: auto 1fr auto;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.state-message > div {
		display: grid;
		gap: var(--space-1);
	}
	.info {
		background: var(--color-info-soft);
		color: var(--color-info);
		border-color: var(--color-info-border);
	}
	.warning {
		background: var(--color-warning-soft);
		color: var(--color-warning);
		border-color: var(--color-warning-border);
	}
	.danger {
		background: var(--color-danger-soft);
		color: var(--color-danger);
		border-color: var(--color-danger-border);
	}
	.success {
		background: var(--color-success-soft);
		color: var(--color-success);
		border-color: var(--color-success-border);
	}
</style>
