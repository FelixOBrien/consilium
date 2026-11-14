---
id: S-01
title: Worklist
route: /
status: planned
priority: P0
features: [F-01, F-02]
stories: [US-01.1, US-01.2, US-01.3]
figma: ""
linear: [SKO-262]
---

# S-01 · Worklist

## Purpose
The pathologist sees the cases waiting for them, browses or filters all cases, and opens one.

## Entry points
- Opening the app.
- The app name in the global bar, from any screen.
- A pathologist's name in a report (F-04.6), which arrives with `view=all&assigned_to=<id>&status=signed_out`.

## Regions

| Region | Contains |
| --- | --- |
| View switch | My cases and All cases, with the count of each. |
| Filters | Status, specialty, assigned pathologist, ICD-10 prefix. A control to clear all. |
| Case list | One row per case: case ID, slide thumbnail, specialty, patient age and sex, status, assigned pathologist, slide count, ICD-10, and for signed-out cases the first line of the conclusion. |
| Pagination | Loads the next 50 when the end of the list is reached. |

## Data

| Region | Route |
| --- | --- |
| View switch, case list | `GET /api/cases` with the view and filters as query parameters |
| Assigned-pathologist filter, roster | `GET /api/pathologists` |
| Acting pathologist | `GET /api/me` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Switch view | List reloads; `view` set in the URL (F-01.4). | `GET /api/cases` |
| Change a filter | List reloads from the first page; filter set in the URL (F-01.5). | `GET /api/cases` |
| Clear filters | All filters removed. | `GET /api/cases` |
| Select a case | Opens S-02 for that case (F-01.6). | — |
| Reach end of list | Next page appended (F-01.1). | `GET /api/cases?cursor=` |
| Change acting pathologist | Identity stored in the browser; My cases reloads (F-01.7). | `GET /api/me`, `GET /api/cases` |

## States
- **Loading** — placeholder rows while the first page loads; existing rows stay visible while a later page loads.
- **Empty, My cases** — says the acting pathologist has no open cases and offers All cases.
- **Empty, filtered** — says no cases match and offers to clear filters.
- **Error** — says the list could not be loaded, with retry. Filters stay as set.
- **No data loaded at all** — says no cases have been ingested and links to S-08.

## Out of scope
- Free-text search results, which are S-07. The global search box is present here as everywhere.
- Sorting other than newest first.
- Editing, assigning or closing cases.
