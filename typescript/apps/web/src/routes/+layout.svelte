<script lang="ts">
	import './layout.css';
	import favicon from '#lib/assets/favicon.svg';
	import AppShell from '#lib/design-system/AppShell.svelte';
	import CasePeek from '#lib/workspace/CasePeek.svelte'; // pragma: allowlist secret
	import { identity } from '#lib/identity/identity.svelte.js';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	void identity.ensureLoaded();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<AppShell>{@render children()}</AppShell>
<CasePeek />
