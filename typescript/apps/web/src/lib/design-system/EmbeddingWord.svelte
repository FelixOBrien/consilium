<script lang="ts">
	let {
		word,
		score,
		active = false,
		onselect
	}: {
		word: string;
		score: number;
		active?: boolean;
		onselect: (word: string) => void;
	} = $props();

	function selectWord(event: MouseEvent) {
		(event.currentTarget as HTMLButtonElement).blur();
		onselect(word);
	}
</script>

<button
	class:active
	data-hint={`Embedding similarity ${score.toFixed(2)} · click to map`}
	aria-label={`Map ${word} on the slide`}
	onclick={selectWord}
>
	{word}
</button>

<style>
	button {
		position: relative;
		display: inline;
		margin: 0;
		padding: 0 var(--space-1);
		border: 0;
		border-radius: var(--radius-xs);
		background: transparent;
		color: inherit;
		font: inherit;
		cursor: pointer;
		transition:
			background var(--motion-fast),
			box-shadow var(--motion-fast),
			color var(--motion-fast);
	}
	button:hover,
	button:focus-visible,
	button.active {
		background: var(--color-action-soft);
		color: var(--color-action);
		box-shadow: inset 0 -0.125rem var(--color-action);
		outline: 0;
	}
	button::after {
		content: attr(data-hint);
		position: absolute;
		z-index: var(--z-dialog);
		left: 50%;
		bottom: calc(100% + var(--space-2));
		width: max-content;
		max-width: 14rem;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-ink);
		color: var(--color-text-inverse);
		font: var(--font-label-xs);
		opacity: 0;
		pointer-events: none;
		transform: translate(-50%, var(--space-1));
		transition:
			opacity var(--motion-fast),
			transform var(--motion-fast);
	}
	button:hover::after,
	button:focus-visible::after {
		opacity: 1;
		transform: translate(-50%, 0);
	}
</style>
