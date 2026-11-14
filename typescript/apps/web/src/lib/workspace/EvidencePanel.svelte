<script lang="ts">
	import {
		Badge,
		Button,
		EmptyState,
		SegmentedControl,
		SelectField,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { evidenceResults, tissueImages } from '#lib/data.js';
	let mode = $state('tissue');
	let query = $state('keratinising atypical nests');
	let specialty = $state('All specialties');
	let scope = $state('corpus');
	let hasQuery = $state(true);
</script>

<div class="panel-content evidence-panel">
	<div class="panel-heading">
		<div>
			<Typography style="eyebrow" tone="accent">S-04 · Evidence</Typography>
			<Typography as="h2" style="section">Retrieve precedent</Typography>
		</div>
		<Button variant="ghost" size="sm" icon="close" onclick={() => (hasQuery = false)}>Clear</Button>
	</div>

	<SegmentedControl
		bind:value={mode}
		items={[
			{ label: 'Tissue', value: 'tissue' },
			{ label: 'Reports', value: 'reports' }
		]}
	/>

	<div class="query-row">
		<TextField
			bind:value={query}
			compact
			icon={mode === 'tissue' ? 'evidence' : 'report'}
			placeholder={mode === 'tissue' ? 'Describe morphology…' : 'Search report text…'}
		/>
		<Button variant="primary" size="sm" icon="search" onclick={() => (hasQuery = true)}
			>Search</Button
		>
	</div>

	<div class="filter-grid">
		<SelectField
			bind:value={specialty}
			compact
			label="Specialty"
			options={['All specialties', 'Dermatopathology', 'Breast', 'Gastrointestinal']}
		/>
		<SelectField bind:value={scope} compact label="Scope" options={['corpus', 'this slide']} />
	</div>

	{#if !hasQuery}
		<EmptyState
			icon="search"
			title="Start from tissue or text"
			description="Select a region in the viewer, search this slide, or describe morphology."
			action="Cases like this slide"
			onaction={() => (hasQuery = true)}
		/>
	{:else}
		<div class="active-query">
			<TissueImage src={tissueImages.wholeSlide} alt="Selected query region" size="md" />
			<div>
				<Typography style="eyebrow" tone="muted">Active region query</Typography>
				<Typography style="small">Selected region · 18 patches averaged</Typography>
			</div>
			<Badge tone="accent">Tissue</Badge>
		</div>

		<div class="results-meta">
			<Typography style="small" tone="secondary">18 cases · 742 ms</Typography>
			<Badge tone="neutral">Other cases only</Badge>
		</div>

		<div class="evidence-list">
			{#each evidenceResults as result (result.id)}
				<article>
					<div class="result-heading">
						<div>
							<Typography as="h3" style="subsection">{result.id}</Typography>
							<div class="meta-row">
								<Typography style="small" tone="secondary">{result.specialty}</Typography>
								<Badge tone="neutral">{result.icd10}</Badge>
							</div>
						</div>
						<span class="match">{Math.round(result.score * 100)}</span>
					</div>
					<div class="patch-strip">
						{#each [result.image, tissueImages.epithelium, tissueImages.stomach] as image, patch (patch)}
							<TissueImage src={image} alt={`Result patch ${patch + 1}`} size="md" />
						{/each}
						<Typography style="small" tone="muted">{result.patchCount} matching patches</Typography>
					</div>
					<Typography style="small">{result.conclusion}</Typography>
					<div class="result-actions">
						<Button variant="secondary" size="sm">Peek</Button>
						<Button
							href={`/cases/${result.id}?panel=report`}
							variant="ghost"
							size="sm"
							icon="external"
						>
							Open
						</Button>
					</div>
				</article>
			{/each}
		</div>

		<Button variant="primary" icon="send">Send 18 cases to consult</Button>
	{/if}
</div>

<style>
	.panel-content {
		display: grid;
		align-content: start;
		gap: var(--space-4);
		padding: var(--space-5);
	}
	.panel-heading,
	.query-row,
	.active-query,
	.results-meta,
	.result-heading,
	.result-actions,
	.patch-strip {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.panel-heading,
	.results-meta,
	.result-heading {
		justify-content: space-between;
	}
	.panel-heading > div,
	.active-query > div,
	.result-heading > div {
		display: grid;
		gap: var(--space-1);
	}
	.query-row :global(.field) {
		flex: 1;
	}
	.filter-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}
	.active-query {
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-action);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
	}
	.active-query > :global(.badge) {
		margin-left: auto;
	}
	.evidence-list {
		display: grid;
	}
	.evidence-list article {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4) 0;
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.match {
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-pill);
		background: var(--color-action-soft);
		color: var(--color-action);
		font: var(--font-label-xs);
	}
	.patch-strip {
		align-items: flex-end;
	}
	.patch-strip :global(.type) {
		margin-left: var(--space-1);
	}
	.result-actions {
		justify-content: flex-end;
	}
</style>
