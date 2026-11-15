<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Badge, Button, Skeleton, StateMessage, TissueImage, Typography } from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import { getActingUserId } from '#lib/identity/acting-user.js';
	import { identity } from '#lib/identity/identity.svelte.js';
	import { specialtyLabel } from '#lib/worklist/query.js';
	import { parseMarkdown, type MarkdownInline } from './consult-markdown.js';
	import {
		AGENT_UNAVAILABLE_COPY,
		AGENT_UNAVAILABLE_TITLE,
		CONSULT_NOTICE,
		buildMessageAttachments,
		casesChipLabel,
		citationLabel,
		consultControllerFor,
		pathologistWorklistHref,
		rankingCountLabel,
		regionChipLabel,
		starterQuestions,
		stepTitle,
		uniqueCitations,
		type Citation,
		type ConsultController,
		type ConsultSnapshot,
		type ConsultViewMessage,
		idleConsultSnapshot
	} from './consult-state.js';
	import { getWorkspaceContext } from './workspace-state.svelte.js'; // pragma: allowlist secret

	const caseState = getWorkspaceContext(); // pragma: allowlist secret

	let snapshot = $state<ConsultSnapshot>(idleConsultSnapshot());
	let controller = $state<ConsultController | null>(null);
	let draft = $state('');
	let threadEl = $state<HTMLDivElement | null>(null);

	const region = $derived(caseState.consultRegionAttachment);
	const caseAttachment = $derived(caseState.consultCasesAttachment);
	const starters = $derived(starterQuestions(caseState.caseDetail?.prior_case_count ?? 0));
	const streaming = $derived(snapshot.phase === 'streaming');
	const showConversation = $derived(
		snapshot.phase === 'ready' ||
			snapshot.phase === 'streaming' ||
			snapshot.phase === 'agent-unavailable'
	);

	$effect(() => {
		const caseId = caseState.caseId;
		const userId = identity.me?.id ?? getActingUserId() ?? '';
		// Re-open when the acting pathologist changes.
		void identity.revision;
		if (!caseId || identity.status === 'loading') return;
		const next = consultControllerFor(caseId, userId);
		controller = next;
		const unsubscribe = next.subscribe((value) => {
			snapshot = value;
		});
		void next.ensureOpen();
		return unsubscribe;
	});

	$effect(() => {
		const last = snapshot.messages.at(-1);
		const token = `${snapshot.messages.length}:${last?.content.length ?? 0}:${last?.steps.length ?? 0}:${last?.status ?? ''}`;
		if (!threadEl) return;
		void token;
		threadEl.scrollTop = threadEl.scrollHeight;
	});

	function submit(content = draft) {
		const text = content.trim();
		if (!text || !controller) return;
		const attachments = buildMessageAttachments(
			region
				? {
						slideId: region.slideId,
						x: region.x,
						y: region.y,
						width: region.width,
						height: region.height,
						label: region.label
					}
				: null,
			caseAttachment?.caseIds ?? null
		);
		if (!controller.beginSend(text, attachments)) return;
		draft = '';
		caseState.consultRegionAttachment = null;
		caseState.consultCasesAttachment = null;
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			submit();
		}
	}

	function openCase(caseId: string) {
		casePeek.open({ caseId });
	}

	function openPathologist(pathologistId: string) {
		const path = resolve('/');
		const query = pathologistWorklistHref(pathologistId).slice(1);
		// Worklist filters are query params, not a typed route id.
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		void goto(`${path}${query}`);
	}

	function slideThumb(slideId: string | null | undefined): string | null {
		if (!slideId) return null;
		return (
			caseState.caseDetail?.slides.find((slide) => slide.id === slideId)?.thumbnail_url ?? null
		);
	}
</script>

{#snippet inlines(nodes: MarkdownInline[], citations: Citation[] | null)}
	{#each nodes as node, index (index)}
		{#if node.type === 'text'}{node.text}{:else if node.type === 'strong'}<strong
				>{@render inlines(node.children, citations)}</strong
			>{:else if node.type === 'em'}<em>{@render inlines(node.children, citations)}</em
			>{:else if node.type === 'code'}<code>{node.text}</code
			>{:else if node.type === 'citation'}<button
				type="button"
				class="citation"
				onclick={() => openCase(node.caseId)}
				aria-label={`Open case ${node.caseId}`}
			>
				{citationLabel(node.caseId, citations)}
			</button>{/if}
	{/each}
{/snippet}

{#snippet answer(source: string, citations: Citation[] | null)}
	{#each parseMarkdown(source) as block, index (index)}
		{#if block.type === 'heading'}
			<Typography as={block.level === 1 ? 'h3' : 'h4'} style="subsection">
				{@render inlines(block.children, citations)}
			</Typography>
		{:else if block.type === 'list'}
			{#if block.ordered}
				<ol>
					{#each block.items as item, itemIndex (itemIndex)}
						<li>{@render inlines(item, citations)}</li>
					{/each}
				</ol>
			{:else}
				<ul>
					{#each block.items as item, itemIndex (itemIndex)}
						<li>{@render inlines(item, citations)}</li>
					{/each}
				</ul>
			{/if}
		{:else if block.type === 'quote'}
			<blockquote>{@render inlines(block.children, citations)}</blockquote>
		{:else if block.type === 'code'}
			<pre><code>{block.text}</code></pre>
		{:else}
			<p>{@render inlines(block.children, citations)}</p>
		{/if}
	{/each}
{/snippet}

{#snippet steps(message: ConsultViewMessage)}
	{#if message.steps.length > 0}
		<div class="steps" data-region="steps">
			{#if message.status === 'streaming'}
				<ol aria-live="polite">
					{#each message.steps as step, index (`${step.tool}-${index}`)}
						<li>
							<span class="step-name">{stepTitle(step.tool)}</span>
							{step.summary}
						</li>
					{/each}
				</ol>
				<Typography style="small" tone="muted">
					{message.content ? 'Writing the answer…' : 'Searching prior cases…'}
				</Typography>
			{:else}
				<Button
					variant="ghost"
					size="sm"
					icon={message.stepsOpen ? 'chevron-down' : 'chevron-right'}
					ariaExpanded={message.stepsOpen}
					onclick={() => controller?.toggleSteps(message.id)}
				>
					{message.stepsOpen ? 'Hide steps' : `Show steps (${message.steps.length})`}
				</Button>
				{#if message.stepsOpen}
					<ol>
						{#each message.steps as step, index (`${step.tool}-${index}`)}
							<li>
								<span class="step-name">{stepTitle(step.tool)}</span>
								{step.summary}
							</li>
						{/each}
					</ol>
				{/if}
			{/if}
		</div>
	{:else if message.status === 'streaming'}
		<Typography style="small" tone="muted">Searching prior cases…</Typography>
	{/if}
{/snippet}

<section class="consult" aria-label="Consult" aria-busy={streaming}>
	<header class="header">
		<div class="header-row">
			<div>
				<Typography style="eyebrow" tone="muted">Consult</Typography>
				<Typography as="h2" style="section">Ask about precedent</Typography>
			</div>
			<Button
				variant="ghost"
				size="sm"
				disabled={snapshot.phase === 'idle' || snapshot.phase === 'loading'}
				onclick={() => void controller?.newThread()}
			>
				New thread
			</Button>
		</div>
		<p class="notice" role="note" data-region="notice">{CONSULT_NOTICE}</p>
	</header>

	<div class="thread" bind:this={threadEl} data-region="conversation" role="log">
		{#if snapshot.phase === 'idle' || snapshot.phase === 'loading'}
			<div class="loading" aria-busy="true">
				<Skeleton height="sm" width="medium" />
				<Skeleton height="lg" />
				<Skeleton height="md" />
			</div>
		{:else if snapshot.phase === 'load-error'}
			<StateMessage
				tone="danger"
				title="The consult thread could not be opened"
				description={snapshot.loadError ?? 'Try again. The rest of this case is still available.'}
				action="Retry"
				onaction={() => void controller?.reload()}
			/>
		{:else if showConversation}
			{#if snapshot.phase === 'agent-unavailable'}
				<div data-region="agent-unavailable">
					<StateMessage
						tone="warning"
						title={AGENT_UNAVAILABLE_TITLE}
						description={AGENT_UNAVAILABLE_COPY}
					/>
				</div>
			{/if}

			{#if snapshot.messages.length === 0}
				<div class="starters" data-region="starters">
					<Typography style="label">Start with a question</Typography>
					<div class="starter-list">
						{#each starters as question, index (question)}
							<Button
								variant={index === 0 ? 'primary' : 'secondary'}
								disabled={streaming}
								onclick={() => submit(question)}
							>
								{question}
							</Button>
						{/each}
					</div>
				</div>
			{/if}

			{#each snapshot.messages as message (message.id)}
				<article class="message {message.role}" data-status={message.status}>
					<Typography style="label" tone={message.role === 'user' ? 'accent' : 'secondary'}>
						{message.role === 'user' ? 'You' : 'Consult'}
					</Typography>

					{#if message.role === 'user' && message.attachments?.region}
						{@const thumb = slideThumb(message.attachments.region.slide_id)}
						<div class="chip static">
							{#if thumb}
								<TissueImage src={thumb} alt="Slide the region was taken from" size="sm" />
							{/if}
							<Typography as="span" style="small">
								{regionChipLabel({
									width: message.attachments.region.width,
									height: message.attachments.region.height
								})}
							</Typography>
						</div>
					{/if}
					{#if message.role === 'user' && message.attachments?.case_ids?.length}
						<div class="chip static">
							<Typography as="span" style="small">
								{casesChipLabel(message.attachments.case_ids.length)}
							</Typography>
						</div>
					{/if}

					{#if message.role === 'assistant'}
						{@render steps(message)}
					{/if}

					{#if message.role === 'user'}
						<p class="user-text">{message.content}</p>
					{:else if message.content}
						<div class="answer" aria-live={message.status === 'streaming' ? 'polite' : undefined}>
							{@render answer(message.content, message.citations)}
						</div>
					{/if}

					{#if message.role === 'assistant'}
						{@const citations = uniqueCitations(message.citations)}
						{#if citations.length > 0}
							<div class="citations" data-region="citations">
								<Typography style="label">Cited cases</Typography>
								<ul>
									{#each citations as item (item.case_id)}
										<li>
											<button
												type="button"
												class="citation"
												onclick={() => openCase(item.case_id)}
												aria-label={`Open case ${item.case_id}`}
											>
												{item.case.specimen_label?.trim() || item.case_id}
											</button>
											<Typography as="span" style="small" tone="muted">{item.case_id}</Typography>
											<Typography as="span" style="small" tone="secondary">
												{specialtyLabel(item.case.specialty)}
											</Typography>
										</li>
									{/each}
								</ul>
							</div>
						{/if}

						{#if message.ranking && message.ranking.length > 0}
							<section class="ranking" data-region="ranking" aria-label="Pathologists to consult">
								<Typography style="label">Pathologists who reported these cases</Typography>
								<ol>
									{#each message.ranking as rank, index (`${rank.pathologist_id}-${index}`)}
										<li>
											<button
												type="button"
												class="rank-link"
												aria-label={`Signed-out cases reported by ${rank.name}`}
												onclick={() => openPathologist(rank.pathologist_id)}
											>
												<span class="rank-index">{index + 1}</span>
												<span class="rank-name">
													<Typography as="span" style="label">{rank.name}</Typography>
													<Badge tone="synthetic">Synthetic</Badge>
												</span>
												<Typography as="span" style="small" tone="secondary">
													{specialtyLabel(rank.specialty)}
												</Typography>
												<span data-case-count={rank.case_count}>
													<Typography as="span" style="small">{rankingCountLabel(rank)}</Typography>
												</span>
											</button>
											{#if rank.case_ids.length > 0}
												<div class="rank-cases">
													{#each rank.case_ids as caseId, caseIndex (`${caseId}-${caseIndex}`)}
														<button
															type="button"
															class="citation"
															onclick={() => openCase(caseId)}
															aria-label={`Open case ${caseId}`}
														>
															{citationLabel(caseId, message.citations)}
														</button>
													{/each}
												</div>
											{/if}
										</li>
									{/each}
								</ol>
							</section>
						{/if}
					{/if}

					{#if message.status === 'error' && message.error && message.error !== message.content.trim()}
						<Typography style="small" tone="danger">{message.error}</Typography>
					{/if}
					{#if message.status === 'error' && message.retry}
						<div>
							<Button variant="secondary" size="sm" onclick={() => controller?.retry(message.id)}>
								Retry
							</Button>
						</div>
					{/if}
					{#if message.status === 'stopped'}
						<Typography style="small" tone="secondary"
							>Stopped. The partial answer is kept.</Typography
						>
					{/if}
				</article>
			{/each}
		{/if}
	</div>

	{#if snapshot.threadId}
		<form
			class="composer"
			data-region="composer"
			onsubmit={(event) => {
				event.preventDefault();
				submit();
			}}
		>
			{#if region || (caseAttachment && caseAttachment.caseIds.length > 0)}
				<div class="chips">
					{#if region}
						{@const thumb = slideThumb(region.slideId)}
						<div class="chip">
							{#if thumb}
								<TissueImage src={thumb} alt="Selected region on the open slide" size="sm" />
							{/if}
							<Typography as="span" style="small">
								{regionChipLabel(region)}
							</Typography>
							<button
								type="button"
								class="chip-remove"
								aria-label="Remove region"
								disabled={streaming}
								onclick={() => (caseState.consultRegionAttachment = null)}
							>
								Remove
							</button>
						</div>
					{/if}
					{#if caseAttachment && caseAttachment.caseIds.length > 0}
						<div class="chip">
							<Typography as="span" style="small">
								{casesChipLabel(caseAttachment.caseIds.length)}
							</Typography>
							<button
								type="button"
								class="chip-remove"
								aria-label="Remove attached cases"
								disabled={streaming}
								onclick={() => (caseState.consultCasesAttachment = null)}
							>
								Remove
							</button>
						</div>
					{/if}
				</div>
			{/if}
			<label class="question">
				<span class="visually-hidden">Question</span>
				<textarea
					rows="3"
					bind:value={draft}
					disabled={streaming || snapshot.phase === 'loading'}
					placeholder="Ask about prior cases"
					onkeydown={onKeydown}></textarea>
			</label>
			<div class="composer-actions">
				{#if streaming}
					<Button variant="danger" size="sm" onclick={() => controller?.stop()}>Stop</Button>
				{:else}
					<Button variant="primary" size="sm" icon="send" type="submit" disabled={!draft.trim()}>
						Send
					</Button>
				{/if}
			</div>
		</form>
	{/if}
</section>

<style>
	.consult {
		display: flex;
		flex-direction: column;
		height: 100%;
		min-height: 100%;
		min-width: 0;
	}
	.header,
	.thread,
	.composer {
		min-width: 0;
	}
	.header {
		display: grid;
		gap: var(--space-3);
		padding: var(--space-4) var(--space-4) var(--space-3);
		border-bottom: var(--border-width) solid var(--color-border);
	}
	.header-row {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.header-row > div:first-child {
		display: grid;
		gap: var(--space-1);
	}
	.notice {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border: var(--border-width) solid var(--color-info-border);
		border-radius: var(--radius-md);
		background: var(--color-info-soft);
		color: var(--color-text-secondary);
		font: var(--font-small);
	}
	.thread {
		display: grid;
		align-content: start;
		gap: var(--space-3);
		flex: 1 1 auto;
		min-height: 0;
		overflow: auto;
		padding: var(--space-4);
	}
	.loading,
	.starters,
	.message,
	.ranking,
	.citations {
		display: grid;
		gap: var(--space-2);
	}
	.starter-list {
		display: grid;
		gap: var(--space-2);
	}
	.starter-list :global(button) {
		justify-content: flex-start;
		height: auto;
		white-space: normal;
		text-align: left;
	}
	.message {
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.message.assistant {
		background: var(--color-surface-raised);
		border-left: 2px solid var(--color-action);
	}
	.user-text {
		margin: 0;
		white-space: pre-wrap;
		font: var(--font-body);
	}
	.answer {
		display: grid;
		gap: var(--space-2);
		font: var(--font-body);
	}
	.answer p,
	.answer ul,
	.answer ol,
	.answer blockquote,
	.answer pre {
		margin: 0;
	}
	.answer ul,
	.answer ol,
	.steps ol {
		padding-left: 1.15rem;
	}
	.answer blockquote {
		padding-left: var(--space-3);
		border-left: 2px solid var(--color-border-strong);
		color: var(--color-text-secondary);
	}
	.answer code {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		font: var(--font-mono);
	}
	.answer pre {
		overflow: auto;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
	}
	.answer pre code {
		padding: 0;
		background: transparent;
	}
	.steps {
		display: grid;
		gap: var(--space-2);
	}
	.steps ol {
		display: grid;
		gap: var(--space-1);
		margin: 0;
	}
	.steps li,
	.citations li {
		font: var(--font-small);
		color: var(--color-text-secondary);
	}
	.step-name {
		color: var(--color-text);
		font: var(--font-label);
	}
	.citations ul,
	.ranking ol {
		display: grid;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.citations li,
	.rank-cases {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.ranking {
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.ranking li {
		display: grid;
		gap: var(--space-2);
	}
	.rank-link {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		column-gap: var(--space-2);
		width: 100%;
		padding: 0;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
	.rank-link:hover .rank-name :global(.type) {
		color: var(--color-action);
	}
	.rank-index {
		display: grid;
		place-items: center;
		width: 1.5rem;
		height: 1.5rem;
		border-radius: var(--radius-pill);
		background: var(--color-action-soft);
		color: var(--color-action);
		font: var(--font-label);
	}
	.rank-name {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		grid-column: 2;
	}
	.rank-link :global(.type) {
		grid-column: 2;
	}
	button.citation,
	.chip-remove {
		border: var(--border-width) solid var(--color-action);
		border-radius: var(--radius-pill);
		background: var(--color-action-soft);
		color: var(--color-action);
		font: var(--font-label-xs);
		cursor: pointer;
	}
	button.citation {
		padding: 0 var(--space-2);
		min-height: var(--badge-height);
	}
	button.citation:hover,
	.chip-remove:hover {
		background: var(--color-action);
		color: var(--color-text-inverse);
	}
	.composer {
		display: grid;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-4) var(--space-4);
		border-top: var(--border-width) solid var(--color-border);
		background: var(--color-surface);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		max-width: 100%;
		padding: var(--space-1) var(--space-2);
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
	}
	.chip-remove {
		padding: 0 var(--space-2);
		min-height: 1.25rem;
	}
	.chip-remove:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}
	.question textarea {
		width: 100%;
		min-height: 4.5rem;
		resize: vertical;
		padding: var(--space-3);
		border: var(--border-width) solid var(--color-border-strong);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: var(--font-body);
	}
	.question textarea:focus {
		border-color: var(--color-action);
		box-shadow: var(--shadow-focus);
		outline: 0;
	}
	.question textarea:disabled {
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
	}
	.composer-actions {
		display: flex;
		justify-content: flex-end;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
	button.citation:focus-visible,
	.chip-remove:focus-visible,
	.rank-link:focus-visible {
		outline: 2px solid var(--color-action);
		outline-offset: 2px;
	}
</style>
