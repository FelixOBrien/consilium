<script lang="ts">
	let {
		src,
		alt,
		size = 'md',
		zoom = false
	}: {
		src: string;
		alt: string;
		size?: 'sm' | 'md' | 'lg' | 'viewer';
		zoom?: boolean;
	} = $props();
</script>

<span class="tissue {size}" class:zoom>
	<img {src} {alt} />
</span>

<style>
	.tissue {
		display: block;
		overflow: hidden;
		flex: none;
		border-radius: var(--radius-sm);
		background: var(--color-image-placeholder);
		border: var(--border-width) solid var(--color-border);
	}
	img {
		width: 100%;
		height: 100%;
		display: block;
		object-fit: cover;
	}
	.sm {
		width: var(--thumb-sm);
		height: var(--thumb-sm);
	}
	.md {
		width: var(--thumb-md);
		height: var(--thumb-md);
	}
	.lg {
		width: var(--thumb-lg);
		height: var(--thumb-lg);
	}
	.viewer {
		width: 100%;
		height: 100%;
		border: 0;
		border-radius: 0;
	}
	.viewer img {
		object-fit: contain;
		filter: saturate(var(--image-saturation)) contrast(var(--image-contrast));
		transform: scale(var(--viewer-image-scale));
	}
	.viewer.zoom img {
		transform: scale(var(--viewer-image-scale-zoom));
	}
</style>
