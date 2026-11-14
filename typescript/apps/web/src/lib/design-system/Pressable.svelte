<script lang="ts">
	import type { Snippet } from 'svelte';
	let {
		children,
		className = '',
		selected = false,
		onclick,
		ariaLabel,
		role,
		ariaSelected
	}: {
		children: Snippet;
		className?: string;
		selected?: boolean;
		onclick?: (event: MouseEvent) => void;
		ariaLabel?: string;
		role?: 'tab';
		ariaSelected?: boolean;
	} = $props();
</script>

<button
	class={className}
	class:selected
	aria-label={ariaLabel}
	{role}
	aria-selected={ariaSelected}
	{onclick}
>
	{@render children()}
</button>
