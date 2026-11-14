<script lang="ts">
	import { TextField } from '#lib';

	let { value, onchange }: { value: string; onchange: (value: string | null) => void } = $props();

	let draft = $state('');
	let emitted = '';
	let synced = false;

	$effect(() => {
		const external = value.trim().toUpperCase();
		if (!synced) {
			draft = value;
			emitted = external;
			synced = true;
			return;
		}
		if (external === emitted) return;
		draft = value;
		emitted = external;
	});

	$effect(() => {
		const next = draft.trim().toUpperCase();
		if (next === emitted) return;
		const handle = setTimeout(() => {
			emitted = next;
			onchange(next || null);
		}, 300);
		return () => clearTimeout(handle);
	});
</script>

<TextField bind:value={draft} label="ICD-10 prefix" placeholder="C50" compact />
