<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Badge, Button, Dialog, Skeleton, StateMessage, Typography } from '#lib';
	import { casePeek } from '#lib/case-peek.svelte.js';
	import { specialtyLabel, statusLabel } from '#lib/worklist/query.js';
	import ReportView from './ReportView.svelte';
	import { loadCaseDetail, loadCaseReport, type CaseLoad, type ReportLoad } from './report-load.js';
	import { caseOpenQuery, visibleCaseIcd10, type CaseDetail } from './report-text.js';

	const target = $derived(casePeek.target);

	let caseLoad = $state<CaseLoad>({ phase: 'loading' });
	let reportLoad = $state<ReportLoad>({ phase: 'loading' });
	let attempt = $state(0);
	let thumbFailed = $state(false);

	const detail = $derived<CaseDetail | null>(caseLoad.phase === 'ready' ? caseLoad.detail : null);
	const icd10 = $derived(detail ? visibleCaseIcd10(detail) : null);
	const signedOut = $derived(detail?.status === 'signed_out');

	$effect(() => {
		const current = target;
		const currentAttempt = attempt;
		thumbFailed = false;
		if (!current) return;
		const caseId = current.caseId;
		let cancelled = false;
		caseLoad = { phase: 'loading' };
		reportLoad = { phase: 'loading' };
		void loadCaseDetail(caseId).then((result) => {
			if (cancelled) return;
			void currentAttempt;
			caseLoad = result;
		});
		void loadCaseReport(caseId).then((result) => {
			if (cancelled) return;
			reportLoad = result;
		});
		return () => {
			cancelled = true;
		};
	});

	function openCase() {
		if (!target) return;
		const path = resolve('/cases/[caseId]', { caseId: target.caseId });
		const query = caseOpenQuery(target.patch);
		casePeek.close();
		if (!query) {
			void goto(path);
			return;
		}
		// The typed route is the case path from resolve(); patch location is query state.
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- query is not part of the route type
		void goto(`${path}?${query}`);
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || !casePeek.target) return;
		event.preventDefault();
		event.stopPropagation();
		casePeek.close();
	}
</script>

<svelte:window onkeydowncapture={onKeydown} />

{#if target}
	<Dialog open title={`Case ${target.caseId}`} onclose={() => casePeek.close()}>
		<div class="peek" data-case-peek={target.caseId}>
			{#if caseLoad.phase === 'loading'}
				<div class="loading" aria-busy="true" aria-label="Loading case">
					<Skeleton width="medium" />
					<Skeleton width="short" height="sm" />
					<Skeleton height="lg" />
				</div>
			{:else if caseLoad.phase === 'not-found'}
				<StateMessage
					tone="warning"
					title="Case not found"
					description="This case is not in the corpus."
				/>
			{:else if caseLoad.phase === 'error'}
				<StateMessage
					tone="danger"
					title="This case could not be loaded."
					action="Retry"
					onaction={() => {
						attempt += 1;
					}}
				/>
			{:else if detail}
				<div class="summary">
					<div class="summary-row">
						<Typography as="h3" style="subsection">{detail.id}</Typography>
						<Badge tone={signedOut ? 'success' : 'warning'}>
							{signedOut ? 'Signed out' : 'Not yet reported'}
						</Badge>
						<Badge tone="info">Not a finding</Badge>
					</div>
					<Typography style="small" tone="secondary">
						{specialtyLabel(detail.specialty)}
						<span aria-hidden="true"> · </span>
						{detail.specimen_label ?? 'Specimen not recorded'}
						<span aria-hidden="true"> · </span>
						{statusLabel(detail.status)}
					</Typography>
					<div class="summary-row">
						<a
							class="patient"
							href={resolve('/patients/[patientId]', { patientId: detail.patient.id })}
						>
							{detail.patient.display_label}
						</a>
						{#if detail.patient.case_count > 1}
							<Typography style="small" tone="muted">{detail.patient.case_count} cases</Typography>
						{/if}
						{#if detail.patient.is_synthetic_linkage}
							<span title="This patient's longitudinal link is synthetic.">
								<Badge tone="synthetic">Synthetic linkage</Badge>
							</span>
						{/if}
						{#if icd10}
							<Typography style="small">ICD-10 {icd10}</Typography>
						{/if}
					</div>
				</div>

				{#if target.patch}
					<figure class="patch">
						{#if thumbFailed}
							<Typography style="small" tone="muted">Patch thumbnail is not available.</Typography>
						{:else}
							<img
								src={`/api/patches/${encodeURIComponent(target.patch.id)}/thumbnail`}
								alt={`Patch ${target.patch.id} from case ${detail.id}`}
								onload={() => {
									thumbFailed = false;
								}}
								onerror={() => {
									thumbFailed = true;
								}}
							/>
						{/if}
						<figcaption>
							<Typography style="small" tone="muted">
								Patch on {target.patch.slide_id}
							</Typography>
						</figcaption>
					</figure>
				{/if}

				<ReportView
					load={reportLoad}
					onretry={() => {
						attempt += 1;
					}}
					peek={{ caseId: detail.id, onopen: openCase }}
					idPrefix="peek-report"
				/>

				<div class="actions">
					<Button variant="primary" onclick={openCase}>Open case</Button>
					<Button variant="ghost" onclick={() => casePeek.close()}>Close</Button>
				</div>
			{/if}
		</div>
	</Dialog>
{/if}

<style>
	.peek {
		display: grid;
		gap: var(--space-4);
		padding-bottom: var(--space-5);
	}
	.loading,
	.summary,
	.patch,
	.actions {
		padding: 0 var(--space-5);
	}
	.summary,
	.summary-row,
	.actions,
	.patch {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.summary,
	.patch {
		display: grid;
		justify-items: start;
	}
	.loading {
		display: grid;
		padding-top: var(--space-5);
	}
	.patient {
		color: var(--color-action);
		font: var(--font-label);
		text-decoration: none;
	}
	.patient:hover {
		text-decoration: underline;
	}
	.patch {
		margin: 0;
	}
	.patch img {
		width: min(100%, 18rem);
		aspect-ratio: 1;
		object-fit: contain;
		border: var(--border-width) solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-image-placeholder);
	}
	.actions {
		padding-top: var(--space-2);
	}
</style>
