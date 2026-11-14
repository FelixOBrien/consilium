<script lang="ts">
	import {
		Avatar,
		Badge,
		Button,
		CheckField,
		EmptyState,
		Icon,
		TextArea,
		TextField,
		Typography
	} from '#lib';
	import { annotations } from '#lib/data.js';
	let tool = $state('rectangle');
	let label = $state('Keratinising focus');
	let note = $state('Central whorl with abrupt eosinophilic maturation.');
	let showForm = $state(true);
	let showLayer = $state(true);
</script>

<div class="panel-content annotation-panel">
	<div class="panel-heading">
		<div>
			<Typography style="eyebrow" tone="accent">S-06 · Annotations</Typography>
			<Typography as="h2" style="section">Slide annotations</Typography>
		</div>
		<CheckField bind:checked={showLayer}>
			<Typography as="span" style="small">Show layer</Typography>
		</CheckField>
	</div>

	<div class="drawing-tools">
		<Typography style="eyebrow" tone="muted">Drawing tool</Typography>
		<div>
			<Button
				variant={tool === 'rectangle' ? 'primary' : 'secondary'}
				size="sm"
				icon="grid"
				onclick={() => {
					tool = 'rectangle';
					showForm = true;
				}}>Rectangle</Button
			>
			<Button
				variant={tool === 'point' ? 'primary' : 'secondary'}
				size="sm"
				icon="plus"
				onclick={() => {
					tool = 'point';
					showForm = true;
				}}>Point</Button
			>
		</div>
	</div>

	{#if showForm}
		<div class="annotation-form">
			<div class="form-heading">
				<div>
					<Typography style="label">New {tool} annotation</Typography>
					<Typography style="small" tone="muted">Region captured from the viewer</Typography>
				</div>
				<Badge tone="accent">Unsaved</Badge>
			</div>
			<TextField bind:value={label} label="Label" icon="annotation" />
			<TextArea bind:value={note} label="Note · optional" rows={3} />
			<div class="form-actions">
				<Button variant="ghost" size="sm" onclick={() => (showForm = false)}>Cancel</Button>
				<Button variant="primary" size="sm">Save annotation</Button>
			</div>
		</div>
	{/if}

	<div class="list-heading">
		<Typography style="eyebrow" tone="muted">On this slide</Typography>
		<Badge tone="neutral">{annotations.length}</Badge>
	</div>

	{#if annotations.length === 0}
		<EmptyState
			icon="annotation"
			title="No annotations yet"
			description="Choose rectangle or point, then place a shape on the slide."
		/>
	{:else}
		<div class="annotation-list">
			{#each annotations as annotation, index (annotation.label)}
				<article class:mine={annotation.author === 'You'}>
					<div class="annotation-heading">
						<span class="annotation-kind"
							><Icon name={index === 0 ? 'grid' : 'plus'} size="sm" /></span
						>
						<div>
							<Typography style="label">{annotation.label}</Typography>
							<Typography style="small" tone="muted"
								>{annotation.kind} · {annotation.time}</Typography
							>
						</div>
						{#if annotation.author === 'You'}<Badge tone="accent">Yours</Badge>{/if}
					</div>
					<Typography style="small">{annotation.note}</Typography>
					<div class="annotation-author">
						<Avatar
							name={annotation.author === 'You' ? 'Dr A. Okafor' : annotation.author}
							size="sm"
						/>
						<Typography style="small" tone="muted">{annotation.author}</Typography>
					</div>
					<div class="annotation-actions">
						<Button size="sm" variant="quiet" icon="external">Go to</Button>
						{#if index === 0}
							<Button size="sm" variant="quiet" icon="evidence">Find similar</Button>
							<Button size="sm" variant="quiet" icon="spark">Ask</Button>
						{/if}
						{#if annotation.author === 'You'}
							<Button size="sm" variant="ghost" icon="more" iconOnly ariaLabel="Edit annotation" />
						{/if}
					</div>
				</article>
			{/each}
		</div>
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
	.form-heading,
	.list-heading,
	.annotation-heading,
	.annotation-author,
	.annotation-actions,
	.form-actions,
	.panel-heading,
	.form-heading,
	.list-heading {
		justify-content: space-between;
	}
	.panel-heading > div,
	.form-heading > div,
	.annotation-heading > div {
		display: grid;
		gap: var(--space-1);
	}
	.drawing-tools {
		display: grid;
		gap: var(--space-2);
	}
	.drawing-tools > div {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-2);
	}
	.annotation-form {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4);
		border: var(--border-width) solid var(--color-action);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
	}
	.form-actions,
	.annotation-actions {
		justify-content: flex-end;
	}
	.annotation-list {
		display: grid;
		gap: var(--space-3);
	}
	.annotation-list article {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.annotation-list article.mine {
		border-color: var(--color-action);
	}
	.annotation-kind {
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-sm);
		background: var(--color-info-soft);
		color: var(--color-info);
	}
	.annotation-heading > :global(.badge) {
		margin-left: auto;
	}
</style>
