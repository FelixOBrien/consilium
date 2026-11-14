<script lang="ts">
	import type { Snippet } from 'svelte';
	import { resolve } from '$app/paths';
	import { Button as ShadButton } from '#lib/components/ui/button/index.js';
	import Icon from './Icon.svelte';

	type IconName =
		| 'activity'
		| 'annotation'
		| 'arrow-left'
		| 'arrow-right'
		| 'chevron-down'
		| 'chevron-right'
		| 'close'
		| 'copy'
		| 'database'
		| 'evidence'
		| 'external'
		| 'filter'
		| 'grid'
		| 'heatmap'
		| 'ingest'
		| 'layers'
		| 'minus'
		| 'more'
		| 'panel'
		| 'plus'
		| 'report'
		| 'search'
		| 'send'
		| 'spark'
		| 'user'
		| 'warning'
		| 'zoom-in'
		| 'zoom-out';

	let {
		children,
		variant = 'secondary',
		size = 'md',
		icon,
		iconOnly = false,
		href,
		disabled = false,
		type = 'button',
		onclick,
		ariaLabel
	}: {
		children?: Snippet;
		variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'quiet';
		size?: 'sm' | 'md' | 'lg';
		icon?: IconName;
		iconOnly?: boolean;
		href?: string;
		disabled?: boolean;
		type?: 'button' | 'submit';
		onclick?: (event: MouseEvent) => void;
		ariaLabel?: string;
	} = $props();

	const shadVariant = $derived(
		variant === 'primary'
			? 'default'
			: variant === 'secondary'
				? 'outline'
				: variant === 'danger'
					? 'destructive'
					: variant === 'quiet'
						? 'secondary'
						: 'ghost'
	);
	const shadSize = $derived(
		iconOnly
			? size === 'sm'
				? 'icon-sm'
				: size === 'lg'
					? 'icon-lg'
					: 'icon'
			: size === 'md'
				? 'default'
				: size
	);
</script>

<ShadButton
	class={`button${iconOnly ? ' icon-only' : ''}`}
	variant={shadVariant}
	size={shadSize}
	href={href ? resolve(href as '/') : undefined}
	{disabled}
	{type}
	{onclick}
	aria-label={ariaLabel}
>
	{#if icon}<Icon name={icon} size={size === 'sm' ? 'sm' : 'md'} />{/if}
	{#if children}{@render children()}{/if}
</ShadButton>
