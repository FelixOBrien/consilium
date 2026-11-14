import { api } from '#lib/api/client.js';
import {
	classifySearchFailure,
	isSlideScopeResponse,
	messageFromEnvelope,
	type BuiltSearch,
	type SearchFailure,
	type SearchResponse,
	type SlideScopeResponse
} from './evidence-model.js';

export type EvidenceCall<T> = {
	status: number;
	data?: T;
	error?: unknown;
};

export type EvidenceTransport = {
	patches(
		body: Extract<BuiltSearch, { endpoint: 'patches' }>['body'],
		signal: AbortSignal
	): Promise<EvidenceCall<SearchResponse | SlideScopeResponse>>;
	reports(
		body: Extract<BuiltSearch, { endpoint: 'reports' }>['body'],
		signal: AbortSignal
	): Promise<EvidenceCall<SearchResponse>>;
};

export type EvidenceResult =
	| {
			ok: true;
			corpus: SearchResponse | null;
			regions: SlideScopeResponse | null;
			notice: string | null;
	  }
	| { ok: false; failure: SearchFailure };

export function liveTransport(): EvidenceTransport {
	return {
		async patches(body, signal): Promise<EvidenceCall<SearchResponse | SlideScopeResponse>> {
			const result = await api.POST('/api/search/patches', { body, signal });
			return {
				status: result.response.status,
				// openapi-typescript widens highlight pairs to number[][].
				data: result.data as (SearchResponse | SlideScopeResponse) | undefined,
				error: result.error
			};
		},
		async reports(body, signal): Promise<EvidenceCall<SearchResponse>> {
			const result = await api.POST('/api/search/reports', { body, signal });
			return {
				status: result.response.status,
				data: result.data as SearchResponse | undefined,
				error: result.error
			};
		}
	};
}

export async function runEvidenceSearch(
	transport: EvidenceTransport,
	built: BuiltSearch,
	signal: AbortSignal
): Promise<EvidenceResult> {
	try {
		if (built.endpoint === 'reports') {
			const result = await transport.reports(built.body, signal);
			if (signal.aborted) return cancelled();
			if (!result.data) {
				return {
					ok: false,
					failure: classifySearchFailure(result.status, messageFromEnvelope(result.error))
				};
			}
			return {
				ok: true,
				corpus: result.data,
				regions: null,
				notice: result.data.notice ?? null
			};
		}
		const result = await transport.patches(built.body, signal);
		if (signal.aborted) return cancelled();
		if (!result.data) {
			return {
				ok: false,
				failure: classifySearchFailure(result.status, messageFromEnvelope(result.error))
			};
		}
		if (isSlideScopeResponse(result.data)) {
			return {
				ok: true,
				corpus: null,
				regions: result.data,
				notice: result.data.notice ?? null
			};
		}
		return {
			ok: true,
			corpus: result.data,
			regions: null,
			notice: result.data.notice ?? null
		};
	} catch {
		if (signal.aborted) return cancelled();
		return { ok: false, failure: { kind: 'error', message: 'The search failed.' } };
	}
}

function cancelled(): EvidenceResult {
	return { ok: false, failure: { kind: 'error', message: 'cancelled' } };
}
