---
id: F-05
title: Evidence search
status: planned
priority: P0
stories: [US-05.1, US-05.2, US-05.3, US-05.4, US-05.5]
models: [patch, slide, report, report_chunk, case, search_hit]
screens: [S-04]
depends_on: [F-03, F-04, F-09]
linear: [SKO-266, SKO-278]
---

# F-05 · Evidence search

## Summary
While viewing a case, a pathologist finds relevant prior cases without leaving it: by pointing at tissue, by describing tissue in words, or by searching report text. Every result is a prior signed-out case with the matching slide region and the report.

## Why
G1 and G3. This is the product's core claim: precedent for what is on screen, retrieved in seconds, checkable against a signed report.

## Scope
**In**
- Five query types, listed below.
- Results grouped by case, with patch locations and report passages.
- Opening a result at its location.

**Out**
- Encoding new images at query time. Queries use stored vectors only.
- Ranking or suggesting a diagnosis from the results.
- Side-by-side comparison view (P2).

## Query types

| # | Query | Input | Vector | Searches |
| --- | --- | --- | --- | --- |
| Q1 | Similar to this patch | `patch_id` | that patch's `embedding` | `patch.embedding` |
| Q2 | Similar to this region | `slide_id` + rectangle | mean of intersecting patches' embeddings, re-normalised | `patch.embedding` |
| Q3 | Cases like this slide | `slide_id` | `slide.embedding` | `slide.embedding` |
| Q4 | Tissue matching a description | text | CONCH-Z text encoding | `patch.embedding` |
| Q5 | Reports matching text | text | bge-small encoding, plus keyword | `report_chunk.embedding`, `report.search_tsv` |

## Behaviour
1. The evidence corpus is signed-out cases only. Open cases, withheld reports and the context case are never returned.
2. Patch queries (Q1, Q2, Q4) retrieve the nearest 200 patches by cosine distance, then group by case. A case's score is its best patch similarity. Each case keeps its top three patches.
3. Q2 with a region covering no patches returns a validation error naming the problem.
4. Q3 returns cases ordered by slide-vector similarity, each with its three patches closest to the query slide's vector.
5. Q5 fuses keyword and semantic ranks by reciprocal rank (constant 60) and returns cases with the best-matching passage.
6. Every case result carries: case ID, specialty, ICD-10, first line of the conclusion, author, score, and for patch queries each patch's slide, coordinates and thumbnail URL.
7. Filters apply before ranking: specialty, stain, ICD-10 prefix. Default is no filter, so matches across organs are allowed.
8. Results return 20 cases by default, at most 50.
9. A patch query with scope `slide` searches only the open slide and returns patches, not cases. This finds other regions of the same slide that look alike (P1).
10. Opening a result navigates to that case with the viewer centred on the patch ([F-03](F03-slide-viewer.md) rule 5). Peeking shows the patch and report without leaving the open case.
11. Hits on the open slide (scope `slide`) are marked on the viewer.
12. The current result set can be handed to the consult agent as context ([F-07](F07-consult-agent.md) rule 9).
13. Patch queries respond within 2 seconds and text queries within 3 seconds on the demo cohort, after the encoders are warm.
14. Similarity is shown as a relative indicator, not as a probability or a percentage of confidence.

## API
- `POST /api/search/patches` — body: one of `patch_id`, `region {slide_id, x, y, width, height}`, `slide_id`, `text`; plus `context_case_id`, `scope` (`corpus` | `slide`), `filters`, `limit`. Returns [search_hit](../models/search_hit.md) results.
- `POST /api/search/reports` — body: `text`, `mode` (`hybrid` | `keyword` | `semantic`), `context_case_id`, `filters`, `limit`.
- `GET /api/cases/{id}/similar` — shortcut for Q3 on the case's first slide and Q5 on its report or clinical history; returns both lists.

## Acceptance
- Selecting a patch in a demo case returns cases from other cases only, with thumbnails that visibly resemble the selection.
- A text description returns patches, and repeating it with a specialty filter returns only that specialty.
- Opening a result lands on the stored patch coordinates.
- No result ever contains the context case, an open case, or withheld report text.
- Timing in rule 13 holds on the demo cohort.

## Open questions
- Whether case score should be the best patch or the mean of the top three. Decide from [F-10](F10-retrieval-evaluation.md).
