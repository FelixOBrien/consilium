declare module 'bun:test' {
	interface Matchers {
		toBe(expected: unknown): void;
		toEqual(expected: unknown): void;
		toBeNull(): void;
		toBeTruthy(): void;
		toBeFalsy(): void;
		toContain(expected: string): void;
		toBeGreaterThan(expected: number): void;
		toHaveLength(expected: number): void;
	}
	export function describe(name: string, fn: () => void): void;
	export function test(name: string, fn: () => void | Promise<void>): void;
	export function beforeEach(fn: () => void): void;
	export function afterEach(fn: () => void): void;
	export function expect(actual: unknown): Matchers;
}
