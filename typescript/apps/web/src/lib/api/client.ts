import createClient from 'openapi-fetch';
import type { paths } from './schema';

/** Typed client for `/api`. Research prototype, not for clinical use. */
export const api = createClient<paths>({ baseUrl: '' });

export type HealthResponse =
	paths['/api/health']['get']['responses'][200]['content']['application/json'];

export type { paths };
