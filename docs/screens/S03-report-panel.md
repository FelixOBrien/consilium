---
id: S-03
title: Report panel
route: panel in S-02 (panel=report)
status: planned
priority: P0
features: [F-04]
stories: [US-04.1, US-04.2, US-04.3]
figma: ""
linear: [SKO-274]
---

# S-03 · Report panel

## Purpose
The pathologist reads the case's report next to its slide, and uses its wording as a query.

## Entry points
- Default panel when a case is opened.
- The Report entry in the S-02 panel switch.
- The same report view, without the panel frame, appears inside the case peek for other cases (F-04.5).

## Regions

| Region | Contains |
| --- | --- |
| Report header | Author, sign-out date, the mark that both are synthetic. For an open case: the not-yet-reported notice. |
| Sections | Extracted non-empty sections in order (clinical history, gross description, microscopic description, conclusion, additional information, ICD-10) plus access to the full OCR report `body` (shown directly when no post-history sections were extracted). For an open case: clinical history only. |
| Context terms | Informative non-stop words reveal themselves on hover or focus. Selecting one maps its embedding similarity on the open slide. |

## Data

| Region | Route |
| --- | --- |
| Everything | `GET /api/cases/{id}/report` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Hover or focus a target word | Its embedding-target state appears without changing the report text (F-04.4, F-06.2). | — |
| Select a target word | A word-to-patch similarity overlay is drawn on the open slide and names the word (F-06.3, F-06.6). | `POST /api/slides/{id}/heatmap` |
| Clear the active word | The word-to-patch overlay is removed (F-06.7). | — |
| Select the author | Opens S-01 filtered to that pathologist's signed-out cases (F-04.6). | — |

## States
- **Loading** — section placeholders.
- **Not reported** — the notice and clinical history; if clinical history is also empty, the notice alone.
- **Error** — says the report could not be loaded, with retry. The viewer is unaffected.
- **Peek context** — the header also names the case the report belongs to and offers to open it.

## Out of scope
- Editing or writing a report.
- Showing a held-out case's real report anywhere in the UI.
- Printing and export.
