import type { JobStatus } from './types.js';

/** Re-request jobs only while work is queued or running. A few seconds, not a tight loop. */
export const POLL_INTERVAL_MS = 2_500;

const ACTIVE: ReadonlySet<string> = new Set<JobStatus>(['queued', 'running']);

export function isActiveStatus(status: string): boolean {
	return ACTIVE.has(status);
}

export function hasActiveJob(jobs: readonly { status: string }[]): boolean {
	return jobs.some((job) => isActiveStatus(job.status));
}

export type PollPhase = 'idle' | 'active';

export function pollPhase(jobs: readonly { status: string }[]): PollPhase {
	return hasActiveJob(jobs) ? 'active' : 'idle';
}

export type ClockTimer = {
	set(callback: () => void, intervalMs: number): unknown;
	clear(handle: unknown): void;
};

const browserTimer: ClockTimer = {
	set(callback, intervalMs) {
		return setInterval(callback, intervalMs);
	},
	clear(handle) {
		clearInterval(handle as ReturnType<typeof setInterval>);
	}
};

/**
 * One interval while any job is queued or running. `stop` clears it (unmount and idle).
 * Calling `setActive(true)` again does not stack a second timer.
 */
export function createPollScheduler(options: {
	onTick: () => void;
	intervalMs?: number;
	timer?: ClockTimer;
}) {
	const intervalMs = options.intervalMs ?? POLL_INTERVAL_MS;
	const timer = options.timer ?? browserTimer;
	let phase: PollPhase = 'idle';
	let handle: unknown = null;

	function stop(): void {
		if (handle !== null) {
			timer.clear(handle);
			handle = null;
		}
		phase = 'idle';
	}

	function setActive(active: boolean): boolean {
		if (!active) {
			stop();
			return false;
		}
		phase = 'active';
		if (handle === null) handle = timer.set(options.onTick, intervalMs);
		return true;
	}

	function sync(jobs: readonly { status: string }[]): boolean {
		return setActive(hasActiveJob(jobs));
	}

	return {
		setActive,
		sync,
		stop,
		phase: () => phase,
		running: () => handle !== null
	};
}
