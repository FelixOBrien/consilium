<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		children,
		as = 'p',
		style = 'body',
		tone = 'default'
	}: {
		children: Snippet;
		as?: 'h1' | 'h2' | 'h3' | 'h4' | 'p' | 'span' | 'div';
		style?:
			| 'display'
			| 'title'
			| 'section'
			| 'subsection'
			| 'body'
			| 'small'
			| 'label'
			| 'eyebrow'
			| 'mono';
		tone?: 'default' | 'secondary' | 'muted' | 'accent' | 'danger' | 'inverse';
	} = $props();
</script>

<svelte:element this={as} class="type {style} {tone}">{@render children()}</svelte:element>

<style>
	.type {
		margin: 0;
		color: var(--color-text);
	}
	.display {
		font: var(--font-display);
		letter-spacing: var(--tracking-tight);
	}
	.title {
		font: var(--font-title);
		letter-spacing: var(--tracking-tight);
	}
	.section {
		font: var(--font-section);
	}
	.subsection {
		font: var(--font-subsection);
	}
	.body {
		font: var(--font-body);
	}
	.small {
		font: var(--font-small);
	}
	.label {
		font: var(--font-label);
	}
	.eyebrow {
		font: var(--font-eyebrow);
		letter-spacing: var(--tracking-wide);
		text-transform: uppercase;
	}
	.mono {
		font: var(--font-mono);
	}
	.secondary {
		color: var(--color-text-secondary);
	}
	.muted {
		color: var(--color-text-muted);
	}
	.accent {
		color: var(--color-action);
	}
	.danger {
		color: var(--color-danger);
	}
	.inverse {
		color: var(--color-text-inverse);
	}
</style>
