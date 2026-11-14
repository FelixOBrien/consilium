---
id: S-07
title: Search
route: /search
status: planned
priority: P0
features: [F-02, F-12]
stories: [US-02.1, US-02.2, US-02.3]
figma: ""
linear: [SKO-281]
---

# S-07 · Search

## Purpose
The pathologist searches every case from anywhere in the app, by report text or by a description of tissue, and opens a result.

## Entry points
- Submitting the global search box on any screen: arrives with `q` set and `mode=reports`.
- A shared or reloaded search URL.

## Regions

| Region | Contains |
| --- | --- |
| Query | The search text and a mode switch between **Reports** and **Tissue** (F-02.2, F-02.5). |
| Filters | Status, specialty, ICD-10 prefix, optional `patient_id` chip when scoped to a patient (F-02.6, F-12.4). |
| Result list, Reports mode | One entry per case: case ID, patient (`display_label` linking to S-09), specialty, patient age and sex, ICD-10, author, the best-matching passage with matched terms marked, and whether it matched by keyword, meaning or both (F-02.4). |
| Result list, Tissue mode | One entry per case: the same case summary, up to three matching patch thumbnails, and the first line of the conclusion. |
| Result actions | Per result: Peek, Open. |
| Summary | Number of cases found and server time. |

## Data

| Region | Route |
| --- | --- |
| Result list, Reports mode | `POST /api/search/reports` with no `context_case_id` |
| Result list, Tissue mode | `POST /api/search/patches` with `text` and no `context_case_id` |
| Peek | `GET /api/cases/{id}`, `GET /api/cases/{id}/report` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Submit a query | Results load; `q` set in the URL (F-02.1). | per mode |
| Switch mode | The same query runs in the other mode; `mode` set in the URL. | per mode |
| Change a filter | Results reload; filter set in the URL (F-02.6). | per mode |
| Peek | Opens the case peek. | `GET /api/cases/{id}`, `/report` |
| Open a Reports result | Navigates to S-02 for that case with the report panel open. | — |
| Open a Tissue result, or one of its patches | Navigates to S-02 centred on that patch (F-02.8). | — |
| Clear the query | Returns to S-01 (F-02.9). | — |

## States
- **No query** — redirects to S-01.
- **Searching** — progress; previous results stay visible, marked stale.
- **No results** — says nothing matched; suggests the other mode and removing filters.
- **Exact match** — when the query is a case ID or ICD-10 code, the exact matches are listed first and identified as such (F-02.3).
- **Error** — says the search failed, with retry.
- **Truncated text** — in Tissue mode, the API's truncation notice is shown.

## Out of scope
- Search relative to an open case, which is S-04.
- Saved searches and history.
- Showing open cases' report text. Open cases can appear in Reports mode only through an exact case-ID match, and then without report text.
