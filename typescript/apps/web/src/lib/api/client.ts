import createClient from 'openapi-fetch';
import { attachActingUserHeader } from '#lib/identity/acting-user.js';
import type { paths } from './schema';

/**
 * Typed client for `/api`. Research prototype, not for clinical use.
 * The browser uses a same-origin path so the dev server can proxy `/api`.
 * A non-browser runtime needs an absolute base for `Request`.
 */
const baseUrl = typeof window === 'undefined' ? 'http://127.0.0.1' : '';

export const api = createClient<paths>({
	baseUrl,
	fetch: (input: Request) => globalThis.fetch(input)
});

api.use({
	onRequest({ request }) {
		return attachActingUserHeader(request);
	}
});

export type HealthResponse =
	paths['/api/health']['get']['responses'][200]['content']['application/json'];

export type { paths };
