<script lang="ts">
	/**
	 * Consilium mark: three fields of view convening on one point.
	 * `default` sits on light surfaces; `inverse` sits on the ink brand tile.
	 * Exported copies live in static/brand/.
	 */
	let {
		size = 24,
		tone = 'default',
		label
	}: { size?: number | string; tone?: 'default' | 'inverse'; label?: string } = $props();
</script>

<svg
	class="logo-mark"
	class:inverse={tone === 'inverse'}
	viewBox="0 0 96 96"
	width={size}
	height={size}
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : 'true'}
>
	<g class="rings" stroke-width="5">
		<circle cx="48" cy="33" r="26" />
		<circle cx="34" cy="57" r="26" />
		<circle cx="62" cy="57" r="26" />
	</g>
	<circle class="dot" cx="48" cy="49" r="7" />
</svg>

<style>
	.logo-mark {
		display: block;
		flex: none;
	}
	.rings {
		fill: var(--color-action);
		fill-opacity: 0.2;
		stroke: var(--color-ink);
	}
	.dot {
		fill: var(--color-action);
	}
	.inverse .rings {
		fill: currentColor;
		fill-opacity: 0.14;
		stroke: currentColor;
	}
	.inverse .dot {
		fill: #b9afff;
	}
</style>
