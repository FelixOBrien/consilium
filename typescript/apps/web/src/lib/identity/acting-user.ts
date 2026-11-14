/** Browser memory of the acting pathologist (F-01.7, D14). */

export const ACTING_USER_STORAGE_KEY = 'acting-pathologist-id';
export const ACTING_USER_HEADER = 'X-User-Id';

export type ActingUserStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

let actingUserId: string | null = null;

export function getActingUserId(): string | null {
	return actingUserId;
}

export function setActingUserId(id: string | null): void {
	const trimmed = id?.trim() ?? '';
	actingUserId = trimmed || null;
}

function browserStorage(): ActingUserStorage | null {
	if (typeof localStorage === 'undefined') return null;
	return localStorage;
}

export function readStoredActingUserId(
	storage: ActingUserStorage | null = browserStorage()
): string | null {
	const value = storage?.getItem(ACTING_USER_STORAGE_KEY)?.trim() ?? '';
	return value || null;
}

export function writeStoredActingUserId(
	id: string | null,
	storage: ActingUserStorage | null = browserStorage()
): void {
	if (!storage) return;
	const trimmed = id?.trim() ?? '';
	if (trimmed) storage.setItem(ACTING_USER_STORAGE_KEY, trimmed);
	else storage.removeItem(ACTING_USER_STORAGE_KEY);
}

/** Restore the last choice before the first API call. */
export function hydrateActingUser(
	storage: ActingUserStorage | null = browserStorage()
): string | null {
	const stored = readStoredActingUserId(storage);
	setActingUserId(stored);
	return stored;
}

/** Remember a choice in memory and in the browser. */
export function rememberActingUser(
	id: string,
	storage: ActingUserStorage | null = browserStorage()
): void {
	setActingUserId(id);
	writeStoredActingUserId(id, storage);
}

export function forgetActingUser(storage: ActingUserStorage | null = browserStorage()): void {
	setActingUserId(null);
	writeStoredActingUserId(null, storage);
}

/** Attach `X-User-Id` when a pathologist has been chosen or restored. */
export function attachActingUserHeader(request: Request): Request {
	const id = getActingUserId() ?? readStoredActingUserId();
	if (!id) return request;
	if (request.headers.get(ACTING_USER_HEADER) === id) return request;
	const headers = new Headers(request.headers);
	headers.set(ACTING_USER_HEADER, id);
	return new Request(request, { headers });
}
