<script lang="ts">
	import * as ShadAvatar from '#lib/components/ui/avatar/index.js';
	let {
		name,
		size = 'md'
	}: {
		name: string;
		size?: 'sm' | 'md' | 'lg';
	} = $props();
	const initials = $derived(
		name
			.replace('Dr ', '')
			.split(' ')
			.map((part) => part[0])
			.join('')
			.slice(0, 2)
	);
</script>

<ShadAvatar.Root
	size={size === 'md' ? 'default' : size}
	class="consilium-avatar {size}"
	aria-label={name}
>
	<ShadAvatar.Fallback>{initials}</ShadAvatar.Fallback>
</ShadAvatar.Root>

<style>
	:global(.consilium-avatar) {
		background: var(--color-avatar);
		color: var(--color-avatar-text);
		font: var(--font-label-xs);
	}
	:global(.consilium-avatar.md) {
		width: var(--avatar-md);
		height: var(--avatar-md);
	}
	:global(.consilium-avatar.lg) {
		width: var(--avatar-lg);
		height: var(--avatar-lg);
		font: var(--font-label);
	}
</style>
