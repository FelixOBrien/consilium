<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Badge as ShadBadge } from '#lib/components/ui/badge/index.js';
	let {
		children,
		tone = 'neutral'
	}: {
		children: Snippet;
		tone?: 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'synthetic' | 'accent';
	} = $props();
</script>

<ShadBadge
	variant={tone === 'danger' ? 'destructive' : tone === 'neutral' ? 'outline' : 'secondary'}
	class="badge {tone}"
>
	{@render children()}
</ShadBadge>

<style>
	:global(.badge) {
		min-height: var(--badge-height);
		padding: 0 var(--space-2);
		border-radius: var(--radius-pill);
		font: var(--font-label-xs);
		white-space: nowrap;
	}
	:global(.badge.neutral) {
		background: var(--color-surface-raised);
		color: var(--color-text-secondary);
		border-color: var(--color-border);
	}
	:global(.badge.info) {
		background: var(--color-info-soft);
		color: var(--color-info);
	}
	:global(.badge.success) {
		background: var(--color-success-soft);
		color: var(--color-success);
	}
	:global(.badge.warning) {
		background: var(--color-warning-soft);
		color: var(--color-warning);
	}
	:global(.badge.danger) {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	:global(.badge.synthetic) {
		background: var(--color-synthetic-soft);
		color: var(--color-synthetic);
	}
	:global(.badge.accent) {
		background: var(--color-action-soft);
		color: var(--color-action);
	}
</style>
