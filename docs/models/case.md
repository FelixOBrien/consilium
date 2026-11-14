---
model: case
table: path_case
status: planned
written_by: pipeline
used_by: [F-01, F-02, F-03, F-04, F-05, F-07, F-10, F-12]
---

# case

## Purpose
One specimen submission for one patient: the unit a pathologist reports. A patient may have several cases over time; each case has one or more slides and at most one report.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | `{specialty}-{source_case_id}`, for example `thorax-TCGA-38-4631`. Shown to users as the case ID. |
| `patient_id` | `text` FK | no | The patient this specimen belongs to ([patient](patient.md)). |
| `specimen_label` | `text` | yes | Short specimen descriptor, for example `Primary resection` or `Prior core biopsy` (shown on longitudinal timelines, F-12.2). |
| `source_dataset` | `text` | no | TCGA project ID, for example `TCGA-LUAD`. |
| `source_case_id` | `text` | no | GDC case `submitter_id` (or specimen barcode when one donor yields multiple cases), for example `TCGA-38-4631`. |
| `specialty` | `text` | no | `breast`, `thorax`, `colorectal`, `gastrointestinal`, `hematologic` or `skin`. |
| `patient_age` | `integer` | yes | Years, from GDC `demographic.age_at_index` (or derived from `days_to_birth` / `age_at_diagnosis`). |
| `patient_sex` | `text` | yes | `F` or `M`, mapped from GDC `demographic.sex_at_birth`. |
| `primary_diagnosis` | `text` | yes | Primary tumour diagnosis from GDC `diagnoses.primary_diagnosis` (for example `Adenocarcinoma, NOS`). Withheld from the client on open cases. |
| `morphology` | `text` | yes | ICD-O-3 morphology code from GDC `diagnoses.morphology` (for example `8140/3`). Used by retrieval evaluation (F-10); withheld on open cases. |
| `icd10` | `text` | yes | ICD-10 code from GDC `diagnoses.icd_10_code`. Null for held-out cases in anything sent to the client. |
| `status` | `text` | no | `open` (not reported) or `signed_out`. |
| `assigned_to` | `text` FK | no | The pathologist responsible. For signed-out cases, the report author. |
| `accessioned_at` | `timestamptz` | no | When the case arrived. Orders the worklist (F-01.1). |
| `is_held_out` | `boolean` | no | True for cases whose real report is hidden for evaluation (F-09.2). |
| `cohort_tier` | `text` | no | `smoke`, `demo` or `stretch`. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `patient_id` → `patient.id`.
- `assigned_to` → `pathologist.id`.
- Has many `slide`; has zero or one `report`; has many `consult_thread`.

## Indexes
- `(patient_id, accessioned_at desc)` — a patient's longitudinal case history (F-12.1) and patient-scoped search.
- `(status, assigned_to, accessioned_at desc)` — My cases.
- `(specialty, accessioned_at desc)` — filtered worklist.
- `(icd10 text_pattern_ops)` — ICD-10 prefix filter.
- Unique `(source_dataset, source_case_id)`.

## Rules
1. `status = 'open'` exactly when `is_held_out` is true. In the hackathon data, the only open cases are held-out ones.
2. A signed-out case has a report with `status = 'signed'` and `assigned_to = report.author_id`.
3. Open cases are assigned across the roster by specialty, with the demo user receiving at least three.
4. `icd10`, `primary_diagnosis` and `morphology` of a held-out case are stored for evaluation (F-10) but never sent to the client.

## Source
`source_*`, `patient_age`, `patient_sex`, `primary_diagnosis`, `morphology` and `icd10` come from the GDC `cases` endpoint (using the diagnosis entry with `classification_of_tumor = primary` and a reported `primary_diagnosis`). `specialty` is mapped from the TCGA project ([context.md](../context.md#slides-gdc)). `patient_id`, `specimen_label`, `assigned_to` and `accessioned_at` are assigned at stage 7: single-case donors span the 90 days before the hackathon, while multi-case longitudinal patients ([patient](patient.md#source)) have prior signed-out cases spaced 3–24 months earlier than the latest case.

## API shape
`CaseSummary` — `id`, `patient` as `PatientRef`, `specimen_label`, `specialty`, `patient_age`, `patient_sex`, `icd10`, `status`, `assigned_to` as `PathologistRef`, `accessioned_at`, `slide_count`, `thumbnail_url`, `conclusion_line` (first line of `report.conclusion`, falling back to `primary_diagnosis` when the OCR report had no separate diagnosis heading). For an open case `icd10` and `conclusion_line` are null.

`CaseDetail` — `CaseSummary` plus `slides` (list of `SlideSummary`), `report_status`, and `prior_case_count` (count of other cases on the same `patient`).

Never sent: `is_held_out` (the client sees only `status`), `source_*`, `cohort_tier`, `morphology`, and for open cases `icd10` and `primary_diagnosis`.
