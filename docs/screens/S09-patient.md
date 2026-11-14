---
id: S-09
title: Patient
route: /patients/[patientId]
status: planned
priority: P1
features: [F-12, F-02, F-05]
stories: [US-12.1, US-12.2]
figma: ""
linear: [SKO-288]
---

# S-09 · Patient

## Purpose
The pathologist inspects one patient's longitudinal pathology record across all of their cases over time, searches within that patient's reports and slides, and opens or peeks at any case.

## Entry points
- Selecting the patient identifier (`PT-…`) in the case list of S-01, the case header of S-02, a result in S-04 or S-07, or the shared case peek (F-12.1).
- Navigating to Patients (`/patients`, which lists patients and selects or routes to S-09).
- Submitting an exact patient ID in global search (F-02.3).

## Regions

| Region | Contains |
| --- | --- |
| Patient header | Patient `display_label`, sex, approximate birth year, total cases, counts of open and signed-out cases, specialties seen, and — when `is_synthetic_linkage` is true — the synthetic longitudinal linkage disclosure (F-12.7). A way back to the worklist or patient directory. |
| Patient search bar | Search text with a mode switch between **Reports** and **Tissue**, scoped automatically to `filters.patient_id` (F-12.4). Clear returns to the full chronological timeline. |
| Case timeline | All cases belonging to this patient ordered chronologically (`accessioned_at` newest first): case ID, `specimen_label`, accession date, patient age at accession, specialty, status, assigned/reporting pathologist (marked synthetic), slide count and thumbnail(s), and — for signed-out cases only — ICD-10 and `conclusion_line` (F-12.2, F-12.5). |
| Patient search results | Shown when a patient-scoped query is active: matching signed-out cases of this patient with highlighted report passages (Reports mode) or up to three matching patch thumbnails (Tissue mode), plus Peek and Open actions (F-12.4). |

## Data

| Region | Route |
| --- | --- |
| Patient header, case timeline | `GET /api/patients/{id}` |
| Patient directory (when browsing `/patients`) | `GET /api/patients` |
| Patient search results, Reports mode | `POST /api/search/reports` with `filters.patient_id` |
| Patient search results, Tissue mode | `POST /api/search/patches` with `text` and `filters.patient_id` |
| Peek | `GET /api/cases/{id}`, `GET /api/cases/{id}/report` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Peek at a case in the timeline or search results | Opens the shared case peek showing the signed-out report (or clinical history alone for an open case) (F-12.3, F-12.5). | `GET /api/cases/{id}`, `/report` |
| Open a case | Navigates to S-02 for that case (at the matched patch when opened from a Tissue search hit) (F-12.3). | — |
| Submit a patient-scoped query | Searches only this patient's signed-out cases; `q` and `mode` are stored in the URL (F-12.4). | `POST /api/search/reports` or `/patches` |
| Clear patient search | Restores the full chronological timeline. | — |
| Select a reporting pathologist | Opens S-01 filtered to that pathologist's signed-out cases. | — |

## States
- **Loading** — header and timeline placeholders.
- **Patient not found** — says so, with links to the patient directory and S-01.
- **Single-case patient** — shows the one case cleanly and states that no prior specimens are recorded for this patient.
- **Open case in timeline** — marked `Open`, showing specimen metadata and assigned pathologist with no ICD-10 or report conclusion (F-12.5).
- **No search matches** — when a patient-scoped query matches none of the patient's signed-out cases, says so and offers to clear the query or search across all patients in S-07.
- **Error** — says the patient record could not be loaded, with retry.

## Out of scope
- Creating, editing or merging patients.
- Clinical data outside pathology cases, slides and reports.
- Generating an AI diagnosis on the patient page (longitudinal AI summaries happen through the consult agent in S-05 so tool trace and citations are preserved).
