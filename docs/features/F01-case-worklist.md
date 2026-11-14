---
id: F-01
title: Case worklist
status: planned
priority: P0
stories: [US-01.1, US-01.2, US-01.3]
models: [patient, case, pathologist, slide, report]
screens: [S-01]
depends_on: [F-09]
linear: [SKO-264, SKO-262]
---

# F-01 · Case worklist

## Summary
A pathologist sees the cases in the system, starting with the open cases assigned to them, and opens one to work on. They also choose which pathologist they are acting as.

## Why
G1. The worklist is the entry point to every case; time-to-diagnosis starts here.

## Scope
**In**
- Listing and filtering cases.
- Choosing the acting pathologist.

**Out**
- Creating, assigning or closing cases.
- Free-text search, which is [F-02](F02-case-search.md).

## Behaviour
1. The list shows cases ordered by `case.accessioned_at`, newest first, 50 per page, with cursor pagination.
2. Each row shows: case ID, patient (`patient.display_label`, with a prior-case indicator when `patient.case_count > 1`, linking to [S-09](../screens/S09-patient.md)), specialty, patient age and sex, status, assigned pathologist, slide count, the first slide's thumbnail, and ICD-10 code.
3. For a signed-out case the row also shows `conclusion_line` (first line of `report.conclusion`, falling back to `case.primary_diagnosis`). For an open case no report text is shown.
4. Two views: **My cases** (assigned to the acting pathologist, open first) and **All cases**. My cases is the default.
5. Filters combine with AND: status, specialty, assigned pathologist, ICD-10 prefix, optional `patient_id`. Filter state is kept in the URL.
6. Selecting a row opens the case workspace ([F-03](F03-slide-viewer.md)).
7. The acting pathologist is chosen from the roster and remembered in the browser. Every API request carries it as `X-User-Id`. With none chosen, the first roster entry flagged `is_demo_user` is used.
8. The roster and all assignments are synthetic and the UI says so where the roster is shown.

## API
- `GET /api/pathologists` — the roster.
- `GET /api/me` — the acting pathologist resolved from `X-User-Id`.
- `GET /api/cases` — filtered, paginated list. Query: `status`, `specialty`, `assigned_to`, `icd10`, `patient_id`, `limit`, `cursor`.
- `GET /api/cases/{id}` — one case with its slides and report status.

## Acceptance
- With the demo cohort loaded, My cases lists the acting pathologist's open cases and All cases lists every case.
- Filtering by specialty and status changes the list and the URL; reloading the URL restores the same list.
- No row for an open case contains report conclusion text.
- Changing the acting pathologist changes My cases.

## Open questions
None.
