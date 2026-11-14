<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		Avatar,
		Badge,
		Button,
		Dialog,
		EmptyState,
		SegmentedControl,
		SelectField,
		Skeleton,
		StateMessage,
		TextField,
		TissueImage,
		Typography
	} from '#lib';
	import { evidenceResults, tissueImages } from '#lib/data.js';

	let query = $state('keratinising squamous nests');
	let mode = $state('reports');
	let status = $state('Signed out');
	let specialty = $state('All specialties');
	let icd = $state('Any ICD-10');
	let peekOpen = $state(false);
	let selected = $state(evidenceResults[0]);
	let screenState = $state('ready');

	function openPeek(result: (typeof evidenceResults)[number]) {
		selected = result;
		peekOpen = true;
	}

	onMount(() => {
		query = page.url.searchParams.get('q') ?? query;
		mode = page.url.searchParams.get('mode') ?? mode;
		screenState = page.url.searchParams.get('state') ?? 'ready';
	});
</script>

<svelte:head>
	<title>Search · Consilium</title>
</svelte:head>

<div class="page search-page">
	<div class="page-heading">
		<div class="heading-copy">
			<Typography as="span" style="eyebrow" tone="accent">Corpus retrieval</Typography>
			<Typography as="h1" style="display">Search precedent</Typography>
			<Typography tone="secondary">
				Search signed-out cases by report language or a direct description of tissue.
			</Typography>
		</div>
		<Button href="/" variant="ghost" icon="arrow-left">Back to worklist</Button>
	</div>

	<section class="surface search-surface">
		<div class="query-region">
			<SegmentedControl
				bind:value={mode}
				items={[
					{ label: 'Reports', value: 'reports' },
					{ label: 'Tissue', value: 'tissue' }
				]}
			/>
			<div class="query-input">
				<TextField
					bind:value={query}
					icon={mode === 'reports' ? 'report' : 'evidence'}
					placeholder={mode === 'reports'
						? 'Search report language, case ID or ICD-10…'
						: 'Describe tissue morphology…'}
				/>
				<Button variant="primary" icon="search">Search</Button>
			</div>
			<Typography style="small" tone="muted">
				{mode === 'reports'
					? 'Hybrid keyword and semantic retrieval across signed reports.'
					: 'Text is matched directly to stored tissue patch embeddings.'}
			</Typography>
		</div>

		<div class="toolbar">
			<SelectField
				bind:value={status}
				compact
				label="Status"
				options={['Signed out', 'Any status', 'Open']}
			/>
			<SelectField
				bind:value={specialty}
				compact
				label="Specialty"
				options={['All specialties', 'Dermatopathology', 'Breast', 'Thoracic', 'Gastrointestinal']}
			/>
			<SelectField
				bind:value={icd}
				compact
				label="ICD-10 prefix"
				options={['Any ICD-10', 'C44', 'D03', 'C18']}
			/>
			<div class="spacer"></div>
			<Button variant="ghost" size="sm" icon="close">Clear query</Button>
		</div>

		{#if screenState === 'error'}
			<div class="state-wrap">
				<StateMessage
					tone="danger"
					title="Search failed"
					description="The current query and filters have been kept."
					action="Retry"
				/>
			</div>
		{:else if screenState === 'empty'}
			<EmptyState
				title="No signed-out cases matched"
				description="Try the Tissue mode for morphology, or remove a specialty filter."
				action="Try Tissue mode"
				onaction={() => (mode = 'tissue')}
			/>
		{:else if screenState === 'loading'}
			<div class="result-list">
				{#each [0, 1, 2, 3] as row (row)}
					<div class="result-card loading">
						<Skeleton height="xl" width="short" />
						<div><Skeleton width="medium" /><Skeleton /><Skeleton height="sm" /></div>
						<Skeleton height="lg" />
					</div>
				{/each}
			</div>
		{:else}
			<div class="results-heading">
				<div>
					<Typography as="h2" style="section">Best matching cases</Typography>
					<Typography style="small" tone="secondary">
						18 cases · 312 ms server time · ordered by relative relevance
					</Typography>
				</div>
				<Badge tone="info">Query ready</Badge>
			</div>

			<div class="result-list">
				{#each evidenceResults as result, index (result.id)}
					<article class="result-card">
						<div class="rank">{index + 1}</div>
						<div class="result-main">
							<div class="result-title">
								<div>
									<Typography as="h3" style="subsection">{result.id}</Typography>
									<div class="meta-row">
										<Typography style="small" tone="secondary">
											{result.specialty} · {result.ageSex}
										</Typography>
										<Badge tone="neutral">{result.icd10}</Badge>
										{#each result.matchedBy as match (match)}
											<Badge tone={match === 'Morphology' ? 'accent' : 'info'}>{match}</Badge>
										{/each}
									</div>
								</div>
								<div class="score">
									<Typography style="eyebrow" tone="muted">Relative match</Typography>
									<div class="score-track">
										<span style={`--score: ${result.score}`}></span>
									</div>
								</div>
							</div>

							{#if mode === 'reports'}
								<div class="passage">
									<Typography style="eyebrow" tone="muted">Microscopic description</Typography>
									<Typography>
										{result.passage.slice(0, 30)}<mark>{result.passage.slice(30, 69)}</mark
										>{result.passage.slice(69)}
									</Typography>
								</div>
							{:else}
								<div class="patches">
									{#each [result.image, tissueImages.epithelium, tissueImages.stomach] as image, patch (patch)}
										<div>
											<TissueImage
												src={image}
												alt={`Matching tissue patch ${patch + 1}`}
												size="lg"
											/>
											<Typography style="small" tone="muted">Patch {patch + 1}</Typography>
										</div>
									{/each}
									<div class="patch-summary">
										<Typography style="label">{result.patchCount} matching patches</Typography>
										<Typography style="small" tone="secondary">{result.conclusion}</Typography>
									</div>
								</div>
							{/if}

							<div class="result-footer">
								<div class="author">
									<Avatar name={result.pathologist} size="sm" />
									<Typography style="small">{result.pathologist}</Typography>
									<Badge tone="synthetic">Synthetic</Badge>
								</div>
								<div class="result-actions">
									<Button variant="secondary" size="sm" onclick={() => openPeek(result)}
										>Peek</Button
									>
									<Button
										href={`/cases/${result.id}?panel=${mode === 'reports' ? 'report' : 'evidence'}`}
										variant="primary"
										size="sm"
										icon="external"
									>
										Open case
									</Button>
								</div>
							</div>
						</div>
					</article>
				{/each}
			</div>
		{/if}
	</section>
</div>

<Dialog open={peekOpen} title={`Case peek · ${selected.id}`} onclose={() => (peekOpen = false)}>
	<div class="peek">
		<div class="peek-slide">
			<TissueImage src={selected.image} alt={`Selected patch for ${selected.id}`} size="viewer" />
			<div class="peek-marker"></div>
		</div>
		<div class="peek-report">
			<div>
				<Typography style="eyebrow" tone="accent">Signed report</Typography>
				<Typography as="h3" style="section">{selected.id}</Typography>
				<div class="meta-row">
					<Badge tone="neutral">{selected.icd10}</Badge>
					<Typography style="small" tone="secondary">
						{selected.pathologist} · 07 Nov 2026
					</Typography>
					<Badge tone="synthetic">Synthetic author/date</Badge>
				</div>
			</div>
			<div class="report-section">
				<Typography style="eyebrow" tone="muted">Conclusion</Typography>
				<Typography>{selected.conclusion}</Typography>
			</div>
			<div class="report-section">
				<Typography style="eyebrow" tone="muted">Microscopic description</Typography>
				<Typography>{selected.passage}</Typography>
			</div>
			<Button href={`/cases/${selected.id}?panel=report`} variant="primary" icon="external">
				Open full case
			</Button>
		</div>
	</div>
</Dialog>

<style>
	.search-page {
		max-width: 80rem;
	}
	.search-surface {
		overflow: hidden;
	}
	.query-region {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-6);
		background:
			linear-gradient(110deg, var(--color-action-soft), transparent 48%), var(--color-surface);
	}
	.query-input {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: var(--space-3);
	}
	.toolbar :global(.field) {
		min-width: 11rem;
	}
	.results-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-5) var(--space-6) var(--space-3);
	}
	.results-heading > div {
		display: grid;
		gap: var(--space-1);
	}
	.result-list {
		display: grid;
		padding: 0 var(--space-6) var(--space-6);
	}
	.result-card {
		display: grid;
		grid-template-columns: 2.5rem 1fr;
		gap: var(--space-4);
		padding: var(--space-5) 0;
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.result-card:last-child {
		border-bottom: 0;
	}
	.result-card.loading {
		grid-template-columns: 6rem 1fr 8rem;
	}
	.result-card.loading > div {
		display: grid;
		gap: var(--space-2);
	}
	.rank {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
		color: var(--color-text-secondary);
		font: var(--font-label-sm);
	}
	.result-main,
	.result-title {
		display: grid;
		gap: var(--space-4);
	}
	.result-title {
		grid-template-columns: 1fr 10rem;
	}
	.result-title > div:first-child,
	.passage,
	.report-section {
		display: grid;
		gap: var(--space-2);
	}
	.score {
		display: grid;
		align-content: start;
		gap: var(--space-2);
		text-align: right;
	}
	.score-track {
		height: var(--space-2);
		overflow: hidden;
		border-radius: var(--radius-pill);
		background: var(--color-surface-subtle);
	}
	.score-track span {
		display: block;
		width: calc(var(--score) * 100%);
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, var(--color-action), var(--color-score-end));
	}
	.passage {
		padding: var(--space-4);
		border-left: 0.1875rem solid var(--color-action);
		border-radius: 0 var(--radius-md) var(--radius-md) 0;
		background: var(--color-surface-raised);
	}
	mark {
		padding: 0 var(--space-1);
		border-radius: var(--radius-xs);
		background: var(--color-warning-soft);
		color: inherit;
	}
	.patches {
		display: grid;
		grid-template-columns: repeat(3, auto) 1fr;
		gap: var(--space-3);
		align-items: center;
	}
	.patches > div:not(.patch-summary) {
		display: grid;
		gap: var(--space-1);
	}
	.patch-summary {
		display: grid;
		gap: var(--space-2);
		padding-left: var(--space-3);
	}
	.result-footer,
	.author,
	.result-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.result-footer {
		justify-content: space-between;
	}
	.state-wrap {
		padding: var(--space-6);
	}
	.peek {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(20rem, 0.85fr);
		min-height: 32rem;
	}
	.peek-slide {
		position: relative;
		min-height: 32rem;
		background: var(--color-viewer);
	}
	.peek-marker {
		position: absolute;
		top: 38%;
		left: 46%;
		width: 18%;
		height: 20%;
		border: 0.125rem solid var(--color-warning-soft);
		box-shadow: 0 0 0 62.5rem var(--color-peek-mask);
	}
	.peek-report {
		display: grid;
		align-content: start;
		gap: var(--space-6);
		padding: var(--space-6);
	}
	.peek-report > div:first-child {
		display: grid;
		gap: var(--space-2);
	}
	@media (max-width: 760px) {
		.query-input,
		.peek {
			grid-template-columns: 1fr;
		}
		.result-title {
			grid-template-columns: 1fr;
		}
		.score {
			text-align: left;
		}
		.patches {
			grid-template-columns: repeat(3, 1fr);
		}
		.patch-summary {
			grid-column: 1 / -1;
		}
		.result-footer {
			align-items: flex-start;
			flex-direction: column;
		}
	}
</style>
