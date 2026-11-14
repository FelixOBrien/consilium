---
id: S-04
title: Evidence panel
route: panel in S-02 (panel=evidence)
status: planned
priority: P0
features: [F-05]
stories: [US-05.1, US-05.2, US-05.3, US-05.4, US-05.5]
figma: ""
linear: [SKO-278]
---

# S-04 · Evidence panel

## Purpose
The pathologist finds prior cases relevant to the one on screen, by tissue or by text, and inspects each result without losing their place.

## Entry points
- The Evidence entry in the S-02 panel switch: opens with the last query for this case, or empty with the starting actions.
- Find similar tissue from a selected patch, region or annotation: opens and runs that query.
- Find cases like this from selected report text: opens in Reports mode and runs.

## Regions

| Region | Contains |
| --- | --- |
| Query bar | A mode switch between **Tissue** and **Reports**, and a text input. In Tissue mode the text describes morphology (Q4); in Reports mode it searches report text (Q5). |
| Starting actions | Shown before any query: Cases like this slide (Q3), and a prompt to click tissue or draw a region. |
| Active query | What was searched: a patch or region thumbnail, "this slide", or the text. A control to clear it. |
| Filters | Specialty, ICD-10 prefix. A scope switch between other cases and this slide (F-05.9). |
| Result list | One entry per case, best first: case ID, specialty, ICD-10, first line of conclusion, author, relative score indicator, how it matched. For tissue queries, up to three patch thumbnails and the count of matching patches. For report queries, the matching passage with matched terms marked. |
| Result actions | Per result: Peek, Open. Per list: Send results to consult. |
| Footer | Number of cases found and server time. |

## Data

| Region | Route |
| --- | --- |
| Result list, tissue queries | `POST /api/search/patches` with `context_case_id` |
| Result list, report queries | `POST /api/search/reports` with `context_case_id` |
| Cases like this slide | `POST /api/search/patches` with `slide_id` |
| Patch thumbnails | `GET /api/patches/{id}/thumbnail` |
| Peek | `GET /api/cases/{id}`, `GET /api/cases/{id}/report` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Submit text in Tissue mode | Runs Q4; results replace the list (F-05.2). | `POST /api/search/patches` |
| Submit text in Reports mode | Runs Q5 (F-05.5). | `POST /api/search/reports` |
| Cases like this slide | Runs Q3 on the open slide (F-05.4). | `POST /api/search/patches` |
| Change a filter | Re-runs the active query with the filter (F-05.7). | same as active query |
| Switch scope to this slide | Re-runs the patch query on the open slide only; matches are marked on the viewer and listed as regions (F-05.9, F-05.11). | `POST /api/search/patches` |
| Hover a patch thumbnail | Shows it larger. | — |
| Peek | Opens the case peek with the patch and report (F-05.10). | `GET /api/cases/{id}`, `/report` |
| Open | Navigates to S-02 for that case, centred on the patch, with the patch marked (F-05.10). | — |
| Select a region match (this-slide scope) | Viewer moves to that region. | — |
| Send results to consult | Consult panel opens with these cases attached (F-05.12). | — |
| Clear query | Returns to the starting actions. | — |

## States
- **Idle** — starting actions and a one-line explanation of the three ways to search.
- **Searching** — the active query is shown with progress; the previous results stay visible, marked stale.
- **First text query** — a notice that the text encoder is warming up if the request takes longer than expected.
- **No results** — says nothing matched, and suggests removing filters if any are set.
- **Region has no tissue** — the validation message from the API (F-05.3).
- **Error** — says the search failed, with retry. The active query is kept.
- **Truncated text** — the API's notice is shown under the query.

## Out of scope
- Side-by-side comparison of the open slide and a result (P2). Open in a new browser tab serves the purpose.
- Uploading an image to search with.
- Any ordering, grouping or labelling of results by suggested diagnosis.
