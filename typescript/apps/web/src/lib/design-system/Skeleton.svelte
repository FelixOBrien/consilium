<script lang="ts">
	let {
		height = 'md',
		width = 'full'
	}: {
		height?: 'sm' | 'md' | 'lg' | 'xl';
		width?: 'short' | 'medium' | 'full';
	} = $props();
</script>

<span class="skeleton {height} {width}"></span>

<style>
	.skeleton {
		display: block;
		border-radius: var(--radius-sm);
		background: linear-gradient(
			90deg,
			var(--color-skeleton) 25%,
			var(--color-skeleton-highlight) 50%,
			var(--color-skeleton) 75%
		);
		background-size: var(--skeleton-size) 100%;
		animation: shimmer var(--motion-loading) infinite linear;
	}
	.sm {
		height: var(--skeleton-sm);
	}
	.md {
		height: var(--skeleton-md);
	}
	.lg {
		height: var(--skeleton-lg);
	}
	.xl {
		height: var(--skeleton-xl);
	}
	.short {
		width: 30%;
	}
	.medium {
		width: 60%;
	}
	.full {
		width: 100%;
	}
	@keyframes shimmer {
		to {
			background-position: calc(var(--skeleton-size) * -1) 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.skeleton {
			animation: none;
		}
	}
</style>
