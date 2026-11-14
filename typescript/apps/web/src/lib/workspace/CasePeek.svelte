<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Badge, Button, Dialog, Typography } from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';

	const target = $derived(casePeek.target);

	function openCase() {
		if (!target) return;
		const path = resolve('/cases/[caseId]', { caseId: target.caseId });
		if (!target.patch) {
			void goto(path);
			return;
		}
		const params = new URLSearchParams({
			patch: target.patch.id,
			slide: target.patch.slide_id
		});
		// The typed route is the case path from resolve(); patch and slide are query state.
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- query is not part of the route type
		void goto(`${path}?${params.toString()}`);
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape' && casePeek.target) casePeek.close();
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if target}
	<Dialog open title={`Case ${target.caseId}`} onclose={() => casePeek.close()}>
		<div class="peek">
			<Badge tone="info">Not a finding</Badge>
			<Typography>
				A preview of another case. Opening it leaves this one. Nothing here is a diagnosis.
			</Typography>
			{#if target.patch}
				<Typography style="small" tone="secondary">
					Patch {target.patch.id} on {target.patch.slide_id} at ({Math.round(target.patch.x)},
					{Math.round(target.patch.y)}).
				</Typography>
			{/if}
			<Button variant="primary" onclick={openCase}>Open case</Button>
		</div>
	</Dialog>
{/if}

<style>
	.peek {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-5);
	}
</style>
