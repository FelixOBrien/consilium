---
id: F-06
title: Report-context similarity overlay
status: in-progress
priority: P1
stories: [US-06.1, US-06.2, US-06.3, US-06.4]
models: [patch, slide, concept]
screens: [S-02, S-03]
depends_on: [F-03, F-04]
linear: [SKO-267, SKO-275, SKO-289]
---

# F-06 · Report-context similarity overlay

## Summary
A pathologist explores the words already present in the case context or report. Informative target words reveal themselves on hover; selecting one shades the open slide by how closely each patch matches that word's embedding.

## Why
G1 and G3. It turns a sentence in a report into places to look, and lets the pathologist check that a phrase and a region agree.

## Scope
**In**
- One word-to-patch similarity overlay on the open slide.
- Target words from the report context.
- **P2.** Shading that same slide from a selected patch or region, and returning the connected patch of similar tissue.

**Out**
- Model attention maps. The heatmap is embedding similarity between phrase and patch, and the UI says so.
- A curated phrase list, free-text phrase input or negative phrase.
- Threshold and opacity controls.
- Precomputed overlays.
- Several words overlaid at once.

## Behaviour
1. Eligible target words are informative report terms, excluding stop words and punctuation.
2. Target words use a subtle hover and focus state; ordinary words remain plain report text.
3. Selecting a target word encodes that word with the CONCH-Z text tower. Each patch of the open slide is scored by cosine similarity between `patch.embedding` and the word vector.
4. Scores are min-max normalised across the slide to 0–1 before they are returned.
5. The viewer shades patches by score using a fixed visual scale. There are no user-facing threshold or opacity controls.
6. The active overlay names the selected report word and carries the label that this is embedding similarity, not a finding.
7. Selecting another target word replaces the active overlay. The active word can be cleared from the report or viewer.
8. The report remains readable and selectable; embedding targets do not appear as a separate list.
9. **P2.** A patch or a region on the open slide can shade that slide instead of a report word. The query vector is that patch's stored `embedding` ([F-05](F05-evidence-search.md) Q1) or the L2-normalised mean of the embeddings of patches that intersect the region (Q2, [architecture D10](../architecture.md#decisions)). Search and this heatmap call the same function, so both use that vector.
10. **P2.** The request carries exactly one of `text`, `concept_id`, `patch_id` or `region`. `region` is a level-0 rectangle `{slide_id, x, y, width, height}`. A `patch_id` or `region` from a different slide than the path is rejected. `negative_text` is rejected with a patch or region. `grow` is rejected with `text` or `concept_id`. A region that intersects no patches is rejected with the same error as search.
11. **P2.** `grow` defaults to false and applies only to a patch or region. The slide's normalised scores are split with Otsu's method, and the threshold is clamped so it is not above the mean score of the seed patches. The cluster grows by breadth-first search with 8-connectivity on the patch grid (`x // size`, `y // size`, [patch](../models/patch.md) rule 1) from every seed patch, through patches whose score is at least the threshold. Every seed patch is part of the cluster. The response adds `cluster.cells` (`x`, `y`, `size`), `cluster.bbox` (`x`, `y`, `width`, `height`), `cluster.threshold` and `cluster.patch_count`. Embeddings are not returned.
12. **P2.** For a patch or region source, `notice` states that the shading is embedding similarity to the selected tissue, not a finding and not a diagnosis. `text` is empty, because there is no phrase.

## API
- `POST /api/slides/{id}/heatmap` — body `text` is the selected report word. Returns `text`, per-patch `{x, y, size, score}` min-max normalised to 0–1, the highest scores in `top`, and `notice` stating this is embedding similarity, not a finding.
- Optional `concept_id` (from `GET /api/concepts`) may be sent instead of `text`. Optional `negative_text` may accompany either one. This screen sends `text` alone. Those fields keep [architecture D9](../architecture.md#decisions) and [concept](../models/concept.md) available; they are not chips or controls in this feature.
- **P2.** The body accepts exactly one of `text`, `concept_id`, `patch_id` or `region`, plus `grow` (default false). The response adds `source` (`text`, `concept`, `patch` or `region`). When `grow` is true it also adds `cluster`. Scores stay one exact SQL scan of the slide, min-max normalised to 0–1.

## Acceptance
- Hovering an eligible report word reveals that it can be mapped; stop words do not become targets.
- Selecting a target word shades the slide within 2 seconds on a demo slide.
- The viewer names the active word and states that the overlay is similarity, not a finding.
- Clearing the active word removes the overlay.
- **P2.** A `patch_id` request scores that patch 1.0. With `grow` true, a region's seed patches are inside the cluster, the cluster is 8-connected, and its bounding box encloses every cell. `grow` false returns no cluster.
- **P2.** Zero sources, two sources, a patch or region from another slide, `negative_text` with a patch or region, and `grow` with `text` or `concept_id` are rejected. A report-word or concept response is unchanged apart from `source`.

## Open questions
- How eligible target words and their display threshold are represented in the report API contract.
