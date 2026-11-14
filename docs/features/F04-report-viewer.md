---
id: F-04
title: Report viewer
status: planned
priority: P0
stories: [US-04.1, US-04.2, US-04.3]
models: [report, case, pathologist]
screens: [S-03]
depends_on: [F-03]
linear: [SKO-264, SKO-274]
---

# F-04 · Report viewer

## Summary
A pathologist reads the pathology report for a case next to its slide, laid out in the sections a report is written in. The same view shows the report of any other case reached through search.

## Why
G3. The signed report is what makes a retrieved slide region meaningful: it says what a colleague concluded about that tissue.

## Scope
**In**
- Reading a report by section.
- Using selected report text as a query.

**Out**
- Writing or editing a report ([F-11](F11-report-authoring.md), cut).
- Printing or export.

## Behaviour
1. A signed-out case shows its extracted non-empty sections in this order: clinical history, gross description, microscopic description, conclusion, additional information, ICD-10 code, with the full OCR report text (`report.body`) available alongside them (or shown directly as the report text when no post-history headings were matched in the OCR text).
2. The report header shows the author (`report.author_id`), `report.signed_at`, and a mark that author and date are synthetic.
3. An open case shows the clinical history only (when present), with a notice that the case has not been reported. A report with `status = withheld` is never sent to the client.
4. Informative non-stop words in report context reveal an embedding-target state on hover or focus. Selecting one maps that word onto the open slide ([F-06](F06-phrase-heatmaps.md)). Ordinary words remain plain text.
5. The same report view is used when peeking at another case from search results or consult citations. In that context it shows which case it belongs to and a link to open that case.
6. The author's name links to the cases they have reported, as a worklist filter.

## API
- `GET /api/cases/{id}/report` — the report (`body` plus extracted sections) with author, or the clinical history alone with `status: "none"` for an open case.

## Acceptance
- A signed-out demo case shows its non-empty extracted sections in the stated order (or full report body when unsectioned) with author and date.
- An open held-out case shows clinical history (if extracted) and the not-reported notice; the network response contains no full report body, conclusion or microscopic text.
- Hovering an informative report word reveals its embedding-target state, and selecting it maps that word onto the open slide.

## Open questions
None.
