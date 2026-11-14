---
id: F-12
title: Patient longitudinal history
status: planned
priority: P1
stories: [US-12.1, US-12.2, US-12.3]
models: [patient, case, slide, report, report_chunk, patch, search_hit]
screens: [S-01, S-02, S-05, S-07, S-09]
depends_on: [F-01, F-04, F-05, F-07]
linear: [SKO-255, SKO-256, SKO-259, SKO-261, SKO-264, SKO-266, SKO-271, SKO-279, SKO-288]
---

# F-12 · Patient longitudinal history

## Summary
Cases belong to a patient, and one patient can have multiple pathology cases over time (prior biopsies, excisions, recurrences or second specimens). A pathologist opens a patient's record to read their chronological case timeline, filters search to that patient, or asks the consult agent to summarise the patient's previous cases alongside corpus precedent.

## Why
G1, G2 and G3. Reviewing a patient's own prior specimens and who reported them is the very first step in real histopathology sign-out and directly informs both diagnostic confidence and who to consult.

## Scope
**In**
- Grouping cases under a `patient` entity with a readable identifier (`PT-…`).
- Viewing a patient's chronological case timeline, slide thumbnails, reporting pathologists and signed-out conclusions ([S-09](../screens/S09-patient.md)).
- Navigating between a case and its patient from the worklist, case workspace, search results and case peek.
- Filtering report and tissue search to one patient (`filters.patient_id`), and marking same-patient hits in corpus search.
- Agent retrieval and cited summary over the open case's patient history ([F-07](F07-consult-agent.md)).

**Out**
- Creating, editing or merging patient records in the UI.
- Real patient-identifiable demographics, MRNs or dates of birth (all data is de-identified; multi-donor longitudinal pairings are marked synthetic).
- External electronic health record (EHR) data outside pathology cases, slides and reports.

## Behaviour
1. Every case belongs to one `patient` (`path_case.patient_id`). Wherever a case summary is shown (worklist, case header, search results, case peek), the patient's `display_label` is shown and links to the patient page ([S-09](../screens/S09-patient.md)), along with an indicator when the patient has more than one case.
2. The patient page lists all of the patient's cases ordered chronologically (`accessioned_at` newest first), showing for each case: case ID, `specimen_label`, specialty, age at accession, status, assigned/reporting pathologist, slide thumbnails, and — for signed-out cases only — ICD-10 and `conclusion_line`, with Peek and Open actions.
3. From the patient page, the pathologist can browse the patient list or jump directly from any case to S-09, inspect a signed-out report inline via case peek, or open any case in S-02.
4. Search endpoints (`POST /api/search/reports` and `POST /api/search/patches`) accept `filters.patient_id`, restricting keyword, semantic and patch retrieval to signed-out cases of that patient. The patient page offers patient-scoped search across the patient's reports and slides.
5. Open-case withholding rules apply strictly on patient views and patient-scoped tools: an open or held-out case belonging to the patient appears in the timeline as `open` (showing `clinical_history` only if inspected), and never leaks its withheld `body`, `conclusion`, `microscopic_description`, `primary_diagnosis`, `morphology` or `icd10`.
6. When corpus-wide evidence search ([F-05](F05-evidence-search.md)) returns a signed-out prior case belonging to the *same* patient as `context_case_id`, the hit carries `same_patient = true` so the UI and consult agent distinguish the patient's own prior specimen from other patients' precedent.
7. When a patient's longitudinal history was assembled by pairing compatible TCGA donors ([patient](../models/patient.md#source)), `is_synthetic_linkage = true` is shown on the patient header alongside synthetic authorship.

## API
- `GET /api/patients` — paginated list of patients (`q` filter on `id` / `display_label`, optional `multi_case=true`, `limit`, `cursor`).
- `GET /api/patients/{id}` — `PatientDetail`: patient metadata plus chronological list of `CaseSummary` rows (obeying open-case withholding).

Also extends:
- `GET /api/cases` ([F-01](F01-case-worklist.md)) — optional `patient_id` query filter.
- `POST /api/search/reports` and `POST /api/search/patches` ([F-05](F05-evidence-search.md)) — optional `filters.patient_id` and `same_patient` flag on `CaseHit`.

## Acceptance
- Opening a multi-case patient from a case header shows all of that patient's cases in chronological order with signed-out conclusions and no withheld data on open cases.
- Searching within a multi-case patient returns passages or patches from that patient's signed-out cases only.
- Asking the consult agent on an open case of a multi-case patient to "summarise this patient's previous cases" calls the patient-history tool, cites the patient's signed-out prior case(s), and states who reported them.
- Multi-donor longitudinal patients display the synthetic-linkage disclosure badge.

## Open questions
None.
