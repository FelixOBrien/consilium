import { afterEach, describe, expect, test } from 'bun:test';
import { api } from '#lib/api/client.js';
import {
	ACTING_USER_HEADER,
	ACTING_USER_STORAGE_KEY,
	attachActingUserHeader,
	forgetActingUser,
	getActingUserId,
	hydrateActingUser,
	readStoredActingUserId,
	rememberActingUser,
	type ActingUserStorage
} from './acting-user.js';

function memoryStorage(initial?: string): ActingUserStorage & { values: Map<string, string> } {
	const values = new Map<string, string>();
	if (initial) values.set(ACTING_USER_STORAGE_KEY, initial);
	return {
		values,
		getItem(key: string) {
			return values.get(key) ?? null;
		},
		setItem(key: string, value: string) {
			values.set(key, value);
		},
		removeItem(key: string) {
			values.delete(key);
		}
	};
}

afterEach(() => {
	forgetActingUser(memoryStorage());
});

describe('acting pathologist identity', () => {
	test('persists the choice and restores it into the request header', () => {
		const storage = memoryStorage();
		rememberActingUser('path-okafor', storage);
		expect(storage.values.get(ACTING_USER_STORAGE_KEY)).toBe('path-okafor');
		forgetActingUser(memoryStorage());
		expect(getActingUserId()).toBeNull();
		expect(hydrateActingUser(storage)).toBe('path-okafor');
		const request = attachActingUserHeader(new Request('http://localhost/api/cases'));
		expect(request.headers.get(ACTING_USER_HEADER)).toBe('path-okafor');
	});

	test('replaces the stored id when the pathologist changes', () => {
		const storage = memoryStorage('path-okafor');
		rememberActingUser('path-nowak', storage);
		expect(readStoredActingUserId(storage)).toBe('path-nowak');
		expect(getActingUserId()).toBe('path-nowak');
	});

	test('omits the header when nobody has been chosen', () => {
		forgetActingUser(memoryStorage());
		const request = attachActingUserHeader(new Request('http://localhost/api/me'));
		expect(request.headers.get(ACTING_USER_HEADER)).toBeNull();
	});

	test('the API client sends X-User-Id on every request', async () => {
		rememberActingUser('path-singh', memoryStorage());
		const seen: string[] = [];
		const original = globalThis.fetch;
		globalThis.fetch = async (input, init) => {
			const request = new Request(input, init);
			seen.push(request.headers.get(ACTING_USER_HEADER) ?? '');
			return new Response(JSON.stringify({ status: 'ok' }), {
				status: 200,
				headers: { 'content-type': 'application/json' }
			});
		};
		try {
			await api.GET('/api/health');
		} finally {
			globalThis.fetch = original;
		}
		expect(seen).toEqual(['path-singh']);
	});
});
