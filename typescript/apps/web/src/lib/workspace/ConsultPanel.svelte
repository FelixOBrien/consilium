<script lang="ts">
	import {
		Avatar,
		Badge,
		Button,
		CitationLink,
		Icon,
		Pressable,
		StateMessage,
		TextField,
		Typography
	} from '#lib';
	let message = $state('');
	let started = $state(true);
	let stepsOpen = $state(true);
	const rankedPathologists = [
		{
			name: 'Dr M. Laurent',
			specialty: 'Dermatopathology',
			count: 4,
			caseIds: ['011904', '010882', '008411']
		},
		{
			name: 'Dr E. Mensah',
			specialty: 'Dermatopathology',
			count: 2,
			caseIds: ['009671', '007214']
		}
	];
</script>

<div class="consult-panel">
	<div class="panel-heading">
		<div>
			<Typography style="eyebrow" tone="accent">S-05 · Consult</Typography>
			<Typography as="h2" style="section">Ask who to consult</Typography>
		</div>
		<Button variant="ghost" size="sm" icon="plus">New thread</Button>
	</div>

	<StateMessage
		tone="info"
		title="Retrieval agent — not diagnosis"
		description="Answers summarise cited prior cases and SQL-derived reporting counts."
	/>

	{#if !started}
		<div class="starters">
			<Typography style="eyebrow" tone="muted">Starter questions</Typography>
			{#each ['Who should I consult on this case?', 'Summarise similar cases', 'What features distinguished similar cases?'] as starter (starter)}
				<Button variant="quiet" onclick={() => (started = true)}>{starter}</Button>
			{/each}
		</div>
	{:else}
		<div class="conversation">
			<div class="user-message">
				<Typography>Who should I consult on this case?</Typography>
				<div class="attachment">
					<Icon name="grid" size="sm" />
					<Typography style="small">Selected region attached</Typography>
				</div>
			</div>

			<div class="assistant-message">
				<div class="agent-label">
					<span><Icon name="spark" size="sm" /></span>
					<Typography style="label">Consilium retrieval agent</Typography>
				</div>

				<div class="steps">
					<Pressable className="step-toggle" onclick={() => (stepsOpen = !stepsOpen)}>
						<div>
							<Icon name="activity" size="sm" />
							<Typography style="label">4 retrieval steps completed</Typography>
						</div>
						<Icon name={stepsOpen ? 'chevron-down' : 'chevron-right'} size="sm" />
					</Pressable>
					{#if stepsOpen}
						<div class="step-list">
							{#each [['Reviewed case context', '1 open case · 2 slides'], ['Searched by selected morphology', '18 precedent cases'], ['Read the 6 highest-ranked reports', '6 signed reports'], ['Ranked reporting pathologists', 'SQL count complete']] as step, index (step[0])}
								<div>
									<span>{index + 1}</span>
									<div>
										<Typography style="small">{step[0]}</Typography>
										<Typography style="small" tone="muted">{step[1]}</Typography>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<div class="answer">
					<Typography>
						Based on morphologically similar signed-out cases, <strong>Dr M. Laurent</strong> is the
						strongest first consult. They reported four of the most relevant skin cases, including
						<CitationLink>skin-011904</CitationLink>
						and <CitationLink>skin-010882</CitationLink>. Those cases shared irregular keratinising
						nests and a stromal response around the invasive front.
					</Typography>
					<Typography>
						<strong>Dr E. Mensah</strong> is a useful second opinion, with two relevant cases
						showing a more junctional pattern <CitationLink>skin-009671</CitationLink>.
					</Typography>
				</div>

				<div class="ranking-card">
					<div class="ranking-heading">
						<div>
							<Typography style="eyebrow" tone="muted">Who to consult</Typography>
							<Typography style="small" tone="secondary">Counts from ranked case set</Typography>
						</div>
						<Badge tone="synthetic">Synthetic roster</Badge>
					</div>
					{#each rankedPathologists as person, index (person.name)}
						<div class="rank-row">
							<span class="rank">{index + 1}</span>
							<Avatar name={person.name} />
							<div>
								<Typography style="label">{person.name}</Typography>
								<Typography style="small" tone="muted">{person.specialty}</Typography>
							</div>
							<div class="case-chips">
								{#each person.caseIds as caseId (caseId)}<Badge tone="neutral">skin-{caseId}</Badge
									>{/each}
							</div>
							<div class="count">
								<Typography style="title">{person.count}</Typography>
								<Typography style="small" tone="muted">cases</Typography>
							</div>
						</div>
					{/each}
				</div>

				<div class="citations">
					<Typography style="eyebrow" tone="muted">5 cited cases</Typography>
					<Button size="sm" variant="quiet">skin-011904</Button>
					<Button size="sm" variant="quiet">skin-010882</Button>
					<Button size="sm" variant="quiet">skin-009671</Button>
				</div>
			</div>
		</div>
	{/if}

	<div class="composer">
		<div class="attachment-chip">
			<Icon name="grid" size="sm" />
			<Typography style="small">Selected region</Typography>
			<Button variant="ghost" size="sm" icon="close" iconOnly ariaLabel="Remove attachment" />
		</div>
		<div class="compose-row">
			<TextField
				bind:value={message}
				icon="spark"
				placeholder="Ask about precedent or who to consult…"
			/>
			<Button variant="primary" icon="send" iconOnly ariaLabel="Send question" />
		</div>
	</div>
</div>

<style>
	.consult-panel {
		display: grid;
		grid-template-rows: auto auto 1fr auto;
		gap: var(--space-4);
		min-height: 100%;
		padding: var(--space-5);
	}
	.panel-heading,
	.ranking-heading,
	.agent-label,
	.attachment,
	.compose-row,
	.citations {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.panel-heading,
	.ranking-heading {
		justify-content: space-between;
	}
	.panel-heading > div,
	.ranking-heading > div {
		display: grid;
		gap: var(--space-1);
	}
	.starters {
		display: grid;
		align-content: start;
		gap: var(--space-2);
	}
	.starters :global(.button) {
		justify-content: flex-start;
		white-space: normal;
		text-align: left;
	}
	.conversation {
		display: grid;
		align-content: start;
		gap: var(--space-4);
	}
	.user-message {
		display: grid;
		justify-self: end;
		gap: var(--space-2);
		max-width: 86%;
		padding: var(--space-3);
		border-radius: var(--radius-lg) var(--radius-lg) var(--radius-xs) var(--radius-lg);
		background: var(--color-ink);
		color: var(--color-text-inverse);
	}
	.user-message :global(.type) {
		color: inherit;
	}
	.attachment {
		width: fit-content;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-viewer-message);
	}
	.assistant-message {
		display: grid;
		gap: var(--space-4);
	}
	.agent-label > span {
		display: grid;
		place-items: center;
		width: var(--control-sm);
		height: var(--control-sm);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
		color: var(--color-action);
	}
	.steps {
		overflow: hidden;
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.steps :global(button.step-toggle) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--space-3);
		border: 0;
		background: var(--color-surface-raised);
		cursor: pointer;
	}
	.steps :global(button.step-toggle > div) {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.step-list {
		display: grid;
		padding: var(--space-3);
	}
	.step-list > div {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-2);
		padding: var(--space-2) 0;
	}
	.step-list > div > span,
	.rank {
		display: grid;
		place-items: center;
		width: var(--space-5);
		height: var(--space-5);
		border-radius: var(--radius-pill);
		background: var(--color-success-soft);
		color: var(--color-success);
		font: var(--font-label-xs);
	}
	.step-list > div > div {
		display: grid;
		gap: var(--space-1);
	}
	.answer {
		display: grid;
		gap: var(--space-3);
	}
	.ranking-card {
		display: grid;
		overflow: hidden;
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.ranking-heading {
		padding: var(--space-3);
		background: var(--color-surface-raised);
	}
	.rank-row {
		display: grid;
		grid-template-columns: auto auto 1fr auto auto;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3);
		border-top: var(--border-width) solid var(--color-border);
	}
	.rank-row > div:not(.case-chips, .count) {
		display: grid;
		gap: var(--space-1);
	}
	.case-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		justify-content: flex-end;
	}
	.count {
		display: grid;
		text-align: right;
	}
	.citations {
		flex-wrap: wrap;
	}
	.composer {
		position: sticky;
		bottom: 0;
		display: grid;
		gap: var(--space-2);
		padding-top: var(--space-3);
		background: var(--color-surface);
		border-top: var(--border-width) solid var(--color-border);
	}
	.attachment-chip {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: fit-content;
		padding-left: var(--space-2);
		border-radius: var(--radius-md);
		background: var(--color-action-soft);
		color: var(--color-action);
	}
	.compose-row :global(.field) {
		flex: 1;
	}
</style>
