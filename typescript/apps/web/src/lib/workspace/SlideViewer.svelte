<script lang="ts">
	import { Badge, Button, CheckField, Icon, TissueImage, Typography } from '#lib';
	import { tissueImages } from '#lib/data.js';

	let {
		onpanel,
		activeWord,
		onclearword
	}: {
		onpanel: (panel: string) => void;
		activeWord: string | null;
		onclearword: () => void;
	} = $props();

	let zoomed = $state(false);
	let selected = $state(true);
	let annotationsVisible = $state(true);
	let hitsVisible = $state(true);
</script>

<section class="viewer-shell" aria-label="Whole slide viewer">
	<div class="viewer">
		<TissueImage
			src={tissueImages.wholeSlide}
			alt="Histology whole slide view"
			size="viewer"
			zoom={zoomed}
		/>

		{#if activeWord}
			<div class="embedding-overlay">
				<span class="heat h1"></span>
				<span class="heat h2"></span>
				<span class="heat h3"></span>
				<span class="heat h4"></span>
			</div>
			<div class="embedding-banner">
				<span class="embedding-icon"><Icon name="heatmap" size="sm" /></span>
				<div>
					<Typography style="eyebrow" tone="muted">Report context overlay</Typography>
					<Typography style="label">Embedding similarity for “{activeWord}”</Typography>
				</div>
				<Badge tone="info">Not a finding</Badge>
				<Button
					variant="ghost"
					size="sm"
					icon="close"
					iconOnly
					ariaLabel="Clear report word overlay"
					onclick={onclearword}
				/>
			</div>
		{/if}

		{#if hitsVisible}
			<span class="hit hit-a"></span>
			<span class="hit hit-b"></span>
			<span class="hit hit-c"></span>
		{/if}
		{#if annotationsVisible}
			<span class="annotation-box"><span>Keratinising focus</span></span>
		{/if}
		{#if selected}
			<span class="selection">
				<span class="selection-label">Selected region · 1.8 × 1.4 mm</span>
			</span>
			<div class="selection-actions">
				<Button variant="primary" size="sm" icon="evidence" onclick={() => onpanel('evidence')}>
					Find similar tissue
				</Button>
				<Button variant="secondary" size="sm" icon="spark" onclick={() => onpanel('consult')}>
					Ask about region
				</Button>
				<Button
					variant="secondary"
					size="sm"
					icon="annotation"
					onclick={() => onpanel('annotations')}
				>
					Annotate
				</Button>
				<Button
					variant="ghost"
					size="sm"
					icon="close"
					iconOnly
					ariaLabel="Clear selection"
					onclick={() => (selected = false)}
				/>
			</div>
		{/if}

		<div class="viewer-controls">
			<Button
				variant="secondary"
				icon="zoom-in"
				iconOnly
				ariaLabel="Zoom in"
				onclick={() => (zoomed = true)}
			/>
			<Button
				variant="secondary"
				icon="zoom-out"
				iconOnly
				ariaLabel="Zoom out"
				onclick={() => (zoomed = false)}
			/>
			<Button
				variant="secondary"
				icon="grid"
				iconOnly
				ariaLabel="Select region"
				onclick={() => (selected = true)}
			/>
		</div>

		<div class="viewer-meta">
			<Badge tone="neutral">{zoomed ? '20.0×' : '8.4×'}</Badge>
			<div class="scale">
				<span></span><Typography style="small" tone="inverse">200 μm</Typography>
			</div>
		</div>

		<div class="navigator">
			<TissueImage src={tissueImages.wholeSlide} alt="Slide navigator" size="viewer" />
			<span></span>
		</div>

		<div class="layers-popover">
			<div class="layers-title">
				<Icon name="layers" size="sm" />
				<Typography style="label" tone="inverse">Layers</Typography>
			</div>
			<CheckField bind:checked={hitsVisible}>
				<span class="layer-swatch hits"></span>
				<Typography as="span" style="small" tone="inverse">Search hits</Typography>
			</CheckField>
			<CheckField bind:checked={annotationsVisible}>
				<span class="layer-swatch notes"></span>
				<Typography as="span" style="small" tone="inverse">Annotations</Typography>
			</CheckField>
		</div>
	</div>
</section>

<style>
	.viewer-shell,
	.viewer {
		width: 100%;
		height: 100%;
		min-width: 0;
		background: var(--color-viewer);
	}
	.viewer {
		position: relative;
		min-height: var(--viewer-min-height);
		overflow: hidden;
		background:
			radial-gradient(circle at 50% 50%, var(--color-viewer-radial), transparent 50%),
			var(--color-viewer);
	}
	.embedding-overlay,
	.heat {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	.heat {
		border-radius: 50%;
		filter: blur(1.4rem);
		mix-blend-mode: multiply;
	}
	.h1 {
		inset: 30% 44% 36% 35%;
		background: var(--color-heatmap-high);
	}
	.h2 {
		inset: 42% 24% 24% 56%;
		background: var(--color-heatmap-mid);
	}
	.h3 {
		inset: 18% 65% 54% 18%;
		background: var(--color-heatmap-low);
	}
	.h4 {
		inset: 62% 54% 10% 24%;
		background: var(--color-heatmap-mid);
	}
	.embedding-banner {
		position: absolute;
		top: var(--space-4);
		left: 50%;
		display: grid;
		grid-template-columns: auto 1fr auto auto;
		align-items: center;
		gap: var(--space-3);
		min-width: 25rem;
		padding: var(--space-2) var(--space-3);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-lg);
		background: color-mix(in srgb, var(--color-surface) 94%, transparent);
		box-shadow: var(--shadow-lg);
		transform: translateX(-50%);
		backdrop-filter: blur(var(--blur-header));
	}
	.embedding-banner > div {
		display: grid;
		gap: var(--space-1);
	}
	.embedding-icon {
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
		color: var(--color-action);
	}
	.hit {
		position: absolute;
		width: var(--space-3);
		height: var(--space-3);
		border: 0.125rem solid var(--color-text-inverse);
		border-radius: var(--radius-pill);
		background: var(--color-action);
		box-shadow: 0 0 0 var(--space-1) var(--color-hit-ring);
	}
	.hit-a {
		top: 28%;
		left: 36%;
	}
	.hit-b {
		top: 56%;
		left: 63%;
	}
	.hit-c {
		top: 66%;
		left: 31%;
	}
	.annotation-box {
		position: absolute;
		top: 24%;
		left: 55%;
		width: 18%;
		height: 17%;
		border: 0.125rem solid var(--color-info-soft);
	}
	.annotation-box span,
	.selection-label {
		position: absolute;
		bottom: 100%;
		left: -0.125rem;
		padding: var(--space-1) var(--space-2);
		background: var(--color-info);
		color: var(--color-text-inverse);
		font: var(--font-label-xs);
		white-space: nowrap;
	}
	.selection {
		position: absolute;
		top: 41%;
		left: 39%;
		width: 22%;
		height: 24%;
		border: 0.125rem solid var(--color-warning-soft);
		box-shadow:
			0 0 0 var(--space-1) var(--color-selection-ring),
			0 0 0 100vmax var(--color-selection-mask);
	}
	.selection-label {
		background: var(--color-warning);
	}
	.selection-actions {
		position: absolute;
		left: 50%;
		bottom: var(--space-6);
		display: flex;
		gap: var(--space-2);
		padding: var(--space-2);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-lg);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
		transform: translateX(-50%);
		backdrop-filter: blur(var(--blur-header));
	}
	.viewer-controls {
		position: absolute;
		top: var(--space-4);
		left: var(--space-4);
		display: grid;
		gap: var(--space-1);
	}
	.viewer-meta {
		position: absolute;
		left: var(--space-4);
		bottom: var(--space-4);
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-2);
		border-radius: var(--radius-md);
		background: var(--color-viewer-panel);
	}
	.scale {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.scale span {
		width: 4rem;
		height: var(--space-2);
		border: solid var(--color-text-inverse);
		border-width: 0 var(--border-width) var(--border-width);
	}
	.navigator {
		position: absolute;
		top: var(--space-4);
		right: var(--space-4);
		width: 9rem;
		height: 6rem;
		overflow: hidden;
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-md);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
	}
	.navigator > span {
		position: absolute;
		inset: 25% 30%;
		border: var(--border-width) solid var(--color-warning-soft);
		background: var(--color-viewer-fill);
	}
	.layers-popover {
		position: absolute;
		top: 7rem;
		right: var(--space-4);
		display: grid;
		gap: var(--space-2);
		width: 11rem;
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-viewer-border);
		border-radius: var(--radius-md);
		background: var(--color-viewer-panel);
		box-shadow: var(--shadow-lg);
	}
	.layers-title {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.layer-swatch {
		width: var(--space-3);
		height: var(--space-3);
		border-radius: var(--radius-xs);
	}
	.layer-swatch.hits {
		border-radius: var(--radius-pill);
		background: var(--color-action);
	}
	.layer-swatch.notes {
		border: var(--border-width) solid var(--color-info-soft);
	}
	@media (max-width: 760px) {
		.embedding-banner {
			top: auto;
			right: var(--space-3);
			bottom: 5rem;
			left: var(--space-3);
			min-width: 0;
			transform: none;
		}
		.selection-actions {
			left: var(--space-3);
			right: var(--space-3);
			overflow-x: auto;
			transform: none;
		}
		.layers-popover {
			display: none;
		}
	}
</style>
