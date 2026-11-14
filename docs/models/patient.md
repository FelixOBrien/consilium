---
model: patient
table: patient
status: planned
written_by: pipeline
used_by: [F-01, F-02, F-05, F-07, F-09, F-12]
---

# patient

## Purpose
One de-identified patient across one or more pathology cases over time. Grouping cases under a patient lets a pathologist and the consult agent inspect longitudinal history (prior biopsies, excisions, recurrences or second specimens) alongside corpus-wide precedent.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | Readable slug, for example `pt-0042`. Shown to users as the patient ID and medical record display identifier. |
| `display_label` | `text` | no | Short human-readable label shown in headers and lists, for example `PT-0042`. |
| `sex` | `text` | yes | `F` or `M`, from GDC `demographic.sex_at_birth` on the patient's earliest case. |
| `birth_year` | `integer` | yes | Approximate birth year derived from `accessioned_at` minus `patient_age` on the earliest case, so longitudinal cases show consistent age progression. |
| `is_synthetic_linkage` | `boolean` | no | True when multi-case longitudinal history was constructed by pairing compatible TCGA donors; false when all cases come from one GDC donor (`submitter_id`). Shown in the UI (F-12.7). |
| `created_at` | `timestamptz` | no | |

## Relationships
- Has many `path_case` (`path_case.patient_id` → `patient.id`).

## Indexes
- Primary key `id` (also serves exact patient-ID lookup in F-02.3).
- Unique `(display_label)` (case-insensitive via `lower(display_label)`).

## Rules
1. Every `path_case` belongs to exactly one `patient`, so every patient has at least one case.
2. Within one patient, `sex` matches `patient_sex` across their cases when known, and `patient_age` increases monotonically (or stays equal) with `accessioned_at`.
3. A patient may have both `signed_out` prior cases and an `open` (held-out) current case. Withholding rules still apply per case: open cases never expose withheld report text, `primary_diagnosis`, `morphology` or `icd10` on the patient endpoint or to the agent (F-12.5, F-07.8).
4. Whenever two or more TCGA donors are linked into one longitudinal `patient` record, `is_synthetic_linkage` is `true` and disclosed in the UI alongside synthetic authorship.

## Source
Built at pipeline stage 7 ([F-09](../features/F09-ingestion.md)):
- When a single TCGA donor (`submitter_id`) contributes multiple distinct specimen submissions (for example primary tumour `01Z` and metastatic/recurrent `06Z`/`02Z` in GDC), they share one `patient` with `is_synthetic_linkage = false`.
- Because TCGA otherwise provides one patient barcode per donor, stage 7 deterministically pairs about 15–20% of cohort cases (matching sex and clinically plausible longitudinal trajectory: either same-organ prior biopsy → excision/recurrence, or a prior primary followed by a later specimen, ordered chronologically over the 24 months before the hackathon) under shared `patient` rows with `is_synthetic_linkage = true`. At least three open held-out cases in the demo tier belong to multi-case patients so longitudinal consult queries work on open cases out of the box.

## API shape
`PatientRef` — `id`, `display_label`, `sex`, `case_count`, `is_synthetic_linkage`. Embedded in `CaseSummary` and `CaseDetail`.

`PatientSummary` — `PatientRef` plus `latest_accessioned_at`, `open_case_count`, `signed_out_case_count`, `specialties` (distinct list of `specialty` across the patient's cases).

`PatientDetail` — `PatientSummary` plus `birth_year` and `cases` (list of `CaseSummary` ordered chronologically by `accessioned_at` desc, obeying open-case withholding rules).
