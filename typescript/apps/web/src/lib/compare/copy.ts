/** Visible compare copy. Precedent is retrieval context, never a diagnosis. */

export const OPEN_CASE_LABEL = 'Open case';
export const PRECEDENT_LABEL = 'Precedent';

export const COMPARE_FRAMING =
	'Precedent tissue for comparison. This view does not assign a diagnosis.';

export const RELATIVE_SCALE_NOTE =
	'Microns per pixel are unavailable for one slide, so linked zoom matches relative zoom rather than physical scale.';

export const MISSING_COMPARE_TITLE = 'Choose two slides to compare';

export const MISSING_COMPARE_BODY =
	'Open this page with a slide id for the open case and a slide id for the precedent. The left pane is the open case and the right pane is precedent tissue for comparison.';

const FORBIDDEN_PHRASES = [
	'same diagnosis',
	'matching diagnosis',
	'confirms the diagnosis',
	'diagnostic match'
];

export function compareCopyAvoidsDiagnosis(text: string): boolean {
	const lowered = text.toLowerCase();
	return FORBIDDEN_PHRASES.every((phrase) => !lowered.includes(phrase));
}
