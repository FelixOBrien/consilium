/**
 * Case peek shared by evidence, consult and search.
 * SKO-274 replaces the placeholder view; callers only use `casePeek.open`.
 */

export type CasePeekPatch = {
	id: string;
	slide_id: string;
	x: number;
	y: number;
	size?: number;
};

export type CasePeekTarget = {
	caseId: string;
	patch?: CasePeekPatch;
};

class CasePeekStore {
	target = $state<CasePeekTarget | null>(null);

	open(target: CasePeekTarget): void {
		this.target = target;
	}

	close(): void {
		this.target = null;
	}
}

export const casePeek = new CasePeekStore();
