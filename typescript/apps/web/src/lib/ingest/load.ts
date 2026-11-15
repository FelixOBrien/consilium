import { api } from '#lib/api/client.js';
import type { HealthResponse, IngestionJob, IngestionJobCreate } from './types.js';

function messageFrom(error: unknown, status: number, fallback: string): string {
	if (error && typeof error === 'object' && 'error' in error) {
		const body = error.error;
		if (body && typeof body === 'object' && 'message' in body && typeof body.message === 'string') {
			const text = body.message.trim();
			if (text) return text;
		}
	}
	return `${fallback} (${status}).`;
}

export async function listJobs(): Promise<IngestionJob[]> {
	const { data, error, response } = await api.GET('/api/ingestion/jobs');
	if (!response.ok || !data) {
		throw new Error(messageFrom(error, response.status, 'Ingestion jobs could not be loaded'));
	}
	return data;
}

export async function getJob(id: string): Promise<IngestionJob> {
	const { data, error, response } = await api.GET('/api/ingestion/jobs/{job_id}', {
		params: { path: { job_id: id } }
	});
	if (!response.ok || !data) {
		throw new Error(messageFrom(error, response.status, 'Job detail could not be loaded'));
	}
	return data;
}

export async function createJob(body: IngestionJobCreate): Promise<IngestionJob> {
	const { data, error, response } = await api.POST('/api/ingestion/jobs', { body });
	if (!response.ok || !data) {
		throw new Error(messageFrom(error, response.status, 'The job could not be queued'));
	}
	return data;
}

export async function fetchHealth(): Promise<HealthResponse> {
	const { data, error, response } = await api.GET('/api/health');
	if (!response.ok || !data) {
		throw new Error(messageFrom(error, response.status, 'Corpus counts could not be loaded'));
	}
	return data;
}
