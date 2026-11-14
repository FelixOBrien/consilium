<script lang="ts">
	import type { Snippet } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { globalSearchHref } from '#lib/search/query.js';
	import { RESEARCH_NOTICE, SYNTHETIC_ROSTER_NOTICE } from '#lib/identity/copy.js';
	import { identity } from '#lib/identity/identity.svelte.js';
	import { specialtyLabel } from '#lib/worklist/query.js';
	import Avatar from './Avatar.svelte';
	import Badge from './Badge.svelte';
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';
	import TextField from './TextField.svelte';
	import Typography from './Typography.svelte';

	let { children }: { children: Snippet } = $props();
	let query = $state('');
	let rosterOpen = $state(false);
	let seenQuery: string | null = null;
	const currentPath = $derived(page.url.pathname);
	const acting = $derived(identity.me);
	const actingName = $derived(acting?.name ?? 'Acting pathologist');

	$effect(() => {
		if (page.url.pathname !== '/search') return;
		const next = page.url.searchParams.get('q') ?? '';
		if (next === seenQuery) return;
		query = next;
		seenQuery = next;
	});

	function submitSearch(event: SubmitEvent) {
		event.preventDefault();
		const href = globalSearchHref(query);
		if (href === '/') {
			void goto(resolve('/'));
			return;
		}
		void goto(resolve(href as '/'), { reset: false });
	}

	function toggleRoster() {
		rosterOpen = !rosterOpen;
	}

	function choose(id: string) {
		rosterOpen = false;
		void identity.select(id);
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') rosterOpen = false;
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="app-shell">
	<header class="global-header">
		<div class="brand-group">
			<a class="brand" href={resolve('/')}>
				<span class="brand-mark"><Icon name="activity" /></span>
				<span>
					<Typography as="span" style="subsection">Consilium</Typography>
					<Typography as="span" style="eyebrow" tone="muted">Retrieval workspace</Typography>
				</span>
			</a>
			<nav aria-label="Primary navigation">
				<a class:active={currentPath === '/'} href={resolve('/')}>Worklist</a>
				<a class:active={currentPath.startsWith('/patients')} href={resolve('/patients')}
					>Patients</a
				>
				<a class:active={currentPath === '/ingest'} href={resolve('/ingest')}>Ingest</a>
			</nav>
		</div>

		<form class="global-search" aria-label="Search cases" onsubmit={submitSearch}>
			<TextField
				bind:value={query}
				name="q"
				placeholder="Search cases, reports or tissue…"
				compact
			/>
			<Button type="submit" variant="primary" size="sm">Search</Button>
		</form>

		<div class="identity">
			<Button
				variant="ghost"
				size="sm"
				ariaExpanded={rosterOpen}
				ariaLabel={`Acting pathologist: ${actingName}. Roster is synthetic.`}
				onclick={toggleRoster}
			>
				<Avatar name={actingName} size="sm" />
				<span class="identity-copy">
					<Typography as="span" style="label">{actingName}</Typography>
					<Typography as="span" style="small" tone="muted">Acting pathologist</Typography>
				</span>
				<Badge tone="synthetic">Synthetic</Badge>
				<Icon name="chevron-down" size="sm" />
			</Button>
			{#if rosterOpen}
				<button
					class="roster-backdrop"
					type="button"
					aria-label="Close roster"
					onclick={() => (rosterOpen = false)}
				></button>
				<div class="roster-popover" role="listbox" aria-label="Synthetic pathologist roster">
					<Typography style="eyebrow" tone="muted">Act as</Typography>
					{#if identity.status === 'loading'}
						<Typography style="small" tone="muted">Loading roster…</Typography>
					{:else if identity.status === 'error'}
						<Typography style="small" tone="secondary">{identity.error}</Typography>
						<Button variant="secondary" size="sm" onclick={() => identity.retry()}>Retry</Button>
					{:else}
						{#each identity.roster as person (person.id)}
							<button
								class:active={person.id === acting?.id}
								type="button"
								role="option"
								aria-selected={person.id === acting?.id}
								onclick={() => choose(person.id)}
							>
								<Avatar name={person.name} size="sm" />
								<span>
									<Typography as="span" style="label">{person.name}</Typography>
									<Typography as="span" style="small" tone="muted">
										{specialtyLabel(person.primary_specialty)}
										{#if person.is_synthetic}
											· Synthetic{/if}
									</Typography>
								</span>
							</button>
						{/each}
					{/if}
					<Typography style="small" tone="muted">{SYNTHETIC_ROSTER_NOTICE}</Typography>
				</div>
			{/if}
		</div>
	</header>

	<div class="research-notice">
		<Icon name="warning" size="sm" />
		<Typography as="span" style="small">{RESEARCH_NOTICE}</Typography>
	</div>

	<main>{@render children()}</main>
</div>

<style>
	.app-shell {
		min-height: 100dvh;
		background: var(--color-canvas);
		color: var(--color-text);
	}
	.global-header {
		position: sticky;
		top: 0;
		z-index: var(--z-header);
		display: grid;
		grid-template-columns:
			minmax(max-content, 1fr) minmax(var(--search-min), var(--search-max))
			minmax(max-content, 1fr);
		align-items: center;
		gap: var(--space-6);
		min-height: var(--header-height);
		padding: 0 var(--space-6);
		background: color-mix(in srgb, var(--color-surface) 94%, transparent);
		border-bottom: var(--border-width) solid var(--color-border);
		backdrop-filter: blur(var(--blur-header));
	}
	.brand-group,
	.brand,
	nav,
	.identity,
	.identity-copy {
		display: flex;
		align-items: center;
	}
	.brand-group {
		gap: var(--space-8);
	}
	.brand {
		gap: var(--space-3);
		color: var(--color-text);
		text-decoration: none;
	}
	.brand > span:last-child,
	.identity-copy {
		align-items: flex-start;
		flex-direction: column;
		line-height: var(--line-tight);
	}
	.brand-mark {
		display: grid;
		place-items: center;
		width: var(--brand-mark);
		height: var(--brand-mark);
		border-radius: var(--radius-md);
		background: var(--color-ink);
		color: var(--color-text-inverse);
		box-shadow: var(--shadow-sm);
	}
	nav {
		gap: var(--space-1);
	}
	nav a {
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
		text-decoration: none;
	}
	nav a:hover,
	nav a.active {
		background: var(--color-surface-subtle);
		color: var(--color-text);
	}
	.global-search {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-2);
	}
	.global-search :global(.field) {
		min-width: 0;
	}
	.identity {
		position: relative;
		justify-content: flex-end;
	}
	.identity :global(.button) {
		padding-left: var(--space-2);
	}
	.roster-backdrop {
		position: fixed;
		inset: 0;
		z-index: 1;
		border: 0;
		background: transparent;
		cursor: default;
	}
	.roster-popover {
		position: absolute;
		z-index: 2;
		top: calc(100% + var(--space-3));
		right: 0;
		display: grid;
		gap: var(--space-2);
		width: var(--popover-width);
		padding: var(--space-4);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		box-shadow: var(--shadow-lg);
	}
	.roster-popover button {
		display: grid;
		grid-template-columns: auto 1fr;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3);
		border: 0;
		border-radius: var(--radius-md);
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.roster-popover button:hover,
	.roster-popover button.active {
		background: var(--color-surface-subtle);
	}
	.roster-popover button span {
		display: grid;
		gap: var(--space-1);
	}
	.research-notice {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-height: var(--notice-height);
		padding: var(--space-1) var(--space-6);
		background: var(--color-notice);
		color: var(--color-notice-text);
		border-bottom: var(--border-width) solid var(--color-notice-border);
	}
	main {
		min-height: calc(100dvh - var(--header-height) - var(--notice-height));
	}
	@media (max-width: 1080px) {
		.global-header {
			grid-template-columns: auto 1fr auto;
		}
		nav,
		.identity-copy,
		.identity :global(.badge) {
			display: none;
		}
	}
	@media (max-width: 760px) {
		.global-header {
			grid-template-columns: 1fr auto;
			gap: var(--space-3);
			padding: var(--space-3) var(--space-4);
		}
		.global-search {
			grid-column: 1 / -1;
			grid-row: 2;
		}
		.brand > span:last-child {
			display: none;
		}
		.research-notice {
			align-items: flex-start;
			justify-content: flex-start;
			padding: var(--space-2) var(--space-4);
		}
	}
</style>
