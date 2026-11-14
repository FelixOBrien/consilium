---
id: F-02
title: Case search
status: planned
priority: P0
stories: [US-02.1, US-02.2, US-02.3]
models: [case, report, report_chunk, patch, search_hit]
screens: [S-01, S-07]
depends_on: [F-01, F-05]
linear: [SKO-266, SKO-281]
---

# F-02 · Case search

## Summary
From anywhere in the app, a pathologist types a query and gets matching cases. The query can match report text (by keyword and by meaning) or describe tissue, in which case it matches slide patches directly.

## Why
G1 and G3. A pathologist often remembers a case by a phrase or a look, not an ID.

## Scope
**In**
- Global search over signed-out reports and over patches, grouped by case.
- The same filters as the worklist.

**Out**
- Searching relative to an open case. That is [F-05](F05-evidence-search.md), which owns the search routes.
- Saved searches and search history.

## Behaviour
1. One search box is present on every screen. Submitting it opens the search screen with the query in the URL.
2. **Reports** mode (default) runs hybrid search: keyword rank over `report.search_tsv` and semantic rank over `report_chunk.embedding`, fused by reciprocal rank. Results are cases.
3. A query that is exactly a case ID or an ICD-10 code returns that case or the cases with that code first.
4. Each report result shows the case summary and the best-matching passage with the matched terms marked, and whether it matched by keyword, meaning or both.
5. **Tissue** mode encodes the query with the CONCH-Z text tower and searches `patch.embedding`. Results are cases, each with up to three matching patch thumbnails.
6. Filters (status, specialty, ICD-10 prefix) apply in both modes and are kept in the URL.
7. Reports with `status = withheld` are never searched and never returned.
8. Opening a tissue result opens the case with the viewer centred on the patch.
9. An empty query shows the worklist.

## API
Uses `POST /api/search/reports` and `POST /api/search/patches`, defined in [F-05](F05-evidence-search.md), with no `context_case_id`.

## Acceptance
- A distinctive term from a known report's conclusion returns that case in the top three in Reports mode.
- A paraphrase sharing no keywords with a known report returns that case in the top ten.
- A morphology phrase in Tissue mode returns cases with patch thumbnails, and opening one lands on that patch.
- No held-out report text appears in any result.

## Open questions
None.
