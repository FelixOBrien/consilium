import { linkedView, relinkAlignment, type PaneView } from './scale.js';

export type Side = 'left' | 'right';

export type PaneController = {
	read: () => PaneView | null;
	apply: (view: PaneView) => void;
	zoomBy: (factor: number) => void;
};

export type MppPair = Record<Side, number | null>;

/**
 * Linked pan and zoom. Only the pane that owns the current gesture moves the
 * other pane, so applying a view cannot ping-pong back.
 */
export class LinkSession {
	sync: boolean;
	private baseline: Record<Side, PaneView> | null = null;
	private leader: Side | null = null;

	constructor(sync: boolean) {
		this.sync = sync;
	}

	get leading(): Side | null {
		return this.leader;
	}

	setBaseline(left: PaneView, right: PaneView): void {
		this.baseline = { left: { ...left }, right: { ...right } };
	}

	claim(side: Side): void {
		this.leader = side;
	}

	release(): void {
		this.leader = null;
	}

	note(side: Side, view: PaneView): void {
		if (!this.baseline) return;
		this.baseline = { ...this.baseline, [side]: { ...view } };
	}

	observe(side: Side, next: PaneView, mpp: MppPair): { side: Side; view: PaneView } | null {
		if (!this.sync || !this.baseline || this.leader !== side) return null;
		const other: Side = side === 'left' ? 'right' : 'left';
		const view = linkedView({
			sourcePrev: this.baseline[side],
			sourceNext: next,
			targetPrev: this.baseline[other],
			sourceMpp: mpp[side],
			targetMpp: mpp[other]
		});
		this.baseline = {
			...this.baseline,
			[side]: { ...next },
			[other]: { ...view }
		};
		return { side: other, view };
	}

	unlink(): void {
		this.sync = false;
		this.leader = null;
	}

	/** Keep both centres and match the right pane to the left pane's scale. */
	relink(
		left: PaneView,
		right: PaneView,
		leftMpp: number | null,
		rightMpp: number | null
	): PaneView {
		const aligned = relinkAlignment(left, right, leftMpp, rightMpp);
		this.sync = true;
		this.leader = null;
		this.baseline = { left: { ...left }, right: { ...aligned } };
		return aligned;
	}
}
