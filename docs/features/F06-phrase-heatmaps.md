---
id: F-06
title: Phrase heatmaps
status: planned
priority: P1
stories: [US-06.1, US-06.2, US-06.3]
models: [patch, slide, concept]
screens: [S-02, S-03]
depends_on: [F-03, F-04]
linear: [SKO-267, SKO-275]
---

# F-06 · Phrase heatmaps

## Summary
A pathologist picks or types a phrase, such as "tumour necrosis", and the open slide is shaded by how closely each patch matches it. This maps the language of a report onto the regions of the slide it describes.

## Why
G1 and G3. It turns a sentence in a report into places to look, and lets the pathologist check that a phrase and a region agree.

## Scope
**In**
- A heatmap for one phrase on the open slide.
- Phrases from a curated list, free text, or a selection in a report.

**Out**
- Model attention maps. The heatmap is embedding similarity between phrase and patch, and the UI says so.
- Precomputed heatmaps.
- Several phrases overlaid at once.

## Behaviour
1. A phrase is encoded with the CONCH-Z text tower. Each patch of the open slide is scored by cosine similarity between `patch.embedding` and the phrase vector.
2. If a negative phrase is given, its similarity is subtracted from the score. Curated concepts carry their own negative phrase (`concept.negative_prompt`).
3. Scores are min-max normalised across the slide to 0–1 before they are returned.
4. The response lists every patch's coordinates, size and normalised score, plus the ten highest-scoring patches in order.
5. The viewer shades patches by score. The user sets a threshold, below which patches are not shaded, and an opacity. Defaults: threshold 0.7, opacity 0.5.
6. The ten highest-scoring patches are listed; selecting one moves the viewer to it.
7. Curated concepts are shown as one-click chips, filtered to the open case's specialty plus concepts marked general.
8. Text longer than the encoder's 127-token limit is truncated, and the response says it was.
9. Text selected in a report ([F-04](F04-report-viewer.md) rule 4) runs the heatmap with that selection as the phrase.
10. The heatmap carries a label: similarity to the phrase, not a finding.
11. Only one heatmap is active per slide. Starting another replaces it; it can be cleared.

## API
- `GET /api/concepts` — the curated list, optionally filtered by `specialty`.
- `POST /api/slides/{id}/heatmap` — body: `text` or `concept_id`, optional `negative_text`. Returns per-patch scores and the top ten.

## Acceptance
- Clicking a concept chip shades the slide within 2 seconds on a demo slide.
- The top-patches list navigates to regions that are shaded most strongly.
- Raising the threshold reduces the shaded area; clearing removes it.
- A phrase selected in the report produces a heatmap without retyping.

## Open questions
- Which concepts produce convincing maps on HistAI. Curate the chip list from what works on the demo cases.
