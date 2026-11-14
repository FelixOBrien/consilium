<script lang="ts">
	import Typography from './Typography.svelte';
	let {
		value = $bindable(50),
		label
	}: {
		value?: number;
		label: string;
	} = $props();
</script>

<label class="slider">
	<span>
		<Typography as="span" style="small">{label}</Typography>
		<Typography as="span" style="mono" tone="secondary">{value}%</Typography>
	</span>
	<input type="range" bind:value min="0" max="100" />
</label>

<style>
	.slider,
	.slider > span {
		display: grid;
		gap: var(--space-2);
	}
	.slider > span {
		grid-template-columns: 1fr auto;
	}
	input {
		width: 100%;
		accent-color: var(--color-action);
	}
</style>
