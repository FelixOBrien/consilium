<script lang="ts">
	import type { Snippet } from 'svelte';
	import Button from './Button.svelte';
	import Typography from './Typography.svelte';
	let {
		open,
		title,
		onclose,
		children
	}: {
		open: boolean;
		title: string;
		onclose: () => void;
		children: Snippet;
	} = $props();
</script>

{#if open}
	<div class="dialog-backdrop" role="presentation" onclick={onclose}>
		<dialog open class="dialog" aria-label={title} onclick={(event) => event.stopPropagation()}>
			<header>
				<Typography as="h2" style="section">{title}</Typography>
				<Button variant="ghost" icon="close" iconOnly ariaLabel="Close" onclick={onclose} />
			</header>
			<div class="dialog-body">{@render children()}</div>
		</dialog>
	</div>
{/if}

<style>
	.dialog-backdrop {
		position: fixed;
		inset: 0;
		z-index: var(--z-dialog);
		display: grid;
		place-items: center;
		padding: var(--space-6);
		background: var(--color-overlay);
		backdrop-filter: blur(var(--blur-overlay));
	}
	.dialog {
		position: static;
		width: min(var(--dialog-width), 100%);
		margin: 0;
		padding: 0;
		max-height: calc(100dvh - var(--space-12));
		overflow: hidden;
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-xl);
		background: var(--color-surface);
		box-shadow: var(--shadow-xl);
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-5) var(--space-6);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.dialog-body {
		overflow: auto;
		max-height: calc(100dvh - var(--dialog-header) - var(--space-12));
	}
</style>
