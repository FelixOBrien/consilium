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
| Sections | Clinical history, gross description, microscopic description, conclusion, differential diagnosis, additional information, ICD-10, in that order, omitting empty ones. For an open case: clinical history only. |
| Selection actions | Appears when text is selected: Show on slide, Find cases like this. |

## Data

| Region | Route |
| --- | --- |
| Everything | `GET /api/cases/{id}/report` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Select text | Selection actions appear (F-04.4). | — |
| Show on slide | A heatmap for the selected text is drawn on the open slide; the heatmap controls in S-02 show the phrase (F-06.9). | `POST /api/slides/{id}/heatmap` |
| Find cases like this | Evidence panel opens in Reports mode with the selected text as the query (F-05 Q5). | `POST /api/search/reports` |
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
