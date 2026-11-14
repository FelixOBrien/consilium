import { api } from '#lib/api/client.js';
import { clearWorklistTallies } from '#lib/worklist/load.js';
import {
	forgetActingUser,
	getActingUserId,
	hydrateActingUser,
	rememberActingUser
} from './acting-user.js';
import type { Pathologist } from '#lib/worklist/query.js';

/**
 * Acting pathologist for the whole app.
 * The roster is synthetic. The choice is stored in the browser and sent as `X-User-Id`.
 */
export class Identity {
	roster = $state<Pathologist[]>([]);
	me = $state<Pathologist | null>(null);
	status = $state<'loading' | 'ready' | 'error'>('loading');
	error = $state<string | null>(null);
	/** Changes when the acting pathologist changes, so lists refetch. */
	revision = $state(0);

	#pending: Promise<void> | null = null;

	ensureLoaded(): Promise<void> {
		if (!this.#pending) this.#pending = this.#load();
		return this.#pending;
	}

	retry(): Promise<void> {
		this.#pending = null;
		return this.ensureLoaded();
	}

	async select(id: string): Promise<void> {
		const chosen = this.roster.find((person) => person.id === id);
		if (!chosen || this.me?.id === id) return;
		rememberActingUser(id);
		clearWorklistTallies();
		this.me = chosen;
		this.revision += 1;
		try {
			const confirmed = await fetchMe();
			if (confirmed.id !== id) {
				rememberActingUser(confirmed.id);
				clearWorklistTallies();
				this.me = confirmed;
				this.revision += 1;
			}
		} catch (error) {
			this.status = 'error';
			this.error = messageOf(error);
		}
	}

	async #load(): Promise<void> {
		hydrateActingUser();
		this.status = 'loading';
		this.error = null;
		try {
			await this.#pull(true);
			this.status = 'ready';
		} catch (error) {
			this.status = 'error';
			this.error = messageOf(error);
			this.#pending = null;
		}
	}

	async #pull(allowDemoFallback: boolean): Promise<void> {
		try {
			const [roster, me] = await Promise.all([fetchRoster(), fetchMe()]);
			this.roster = roster;
			this.me = me;
			rememberActingUser(me.id);
		} catch (error) {
			if (allowDemoFallback && getActingUserId()) {
				forgetActingUser();
				await this.#pull(false);
				return;
			}
			throw error;
		}
	}
}

export const identity = new Identity();

async function fetchRoster(): Promise<Pathologist[]> {
	const { data, error, response } = await api.GET('/api/pathologists');
	if (!response.ok || !data) throw new Error(apiMessage(error, response.status));
	return data;
}

async function fetchMe(): Promise<Pathologist> {
	const { data, error, response } = await api.GET('/api/me');
	if (!response.ok || !data) throw new Error(apiMessage(error, response.status));
	return data;
}

function apiMessage(error: unknown, status: number): string {
	if (error && typeof error === 'object' && 'error' in error) {
		const body = error.error;
		if (body && typeof body === 'object' && 'message' in body && typeof body.message === 'string') {
			return body.message;
		}
	}
	return `Could not load the acting pathologist (${status}).`;
}

function messageOf(error: unknown): string {
	return error instanceof Error ? error.message : 'Could not load the acting pathologist.';
}
