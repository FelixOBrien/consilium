---
model: case
table: path_case
status: planned
written_by: pipeline
used_by: [F-01, F-02, F-03, F-04, F-05, F-07, F-10]
---

# case

## Purpose
One specimen submission for one patient: the unit a pathologist reports. A case has one or more slides and at most one report.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | `{specialty}-{source_case_id}`, for example `breast-000412`. Shown to users as the case ID. |
| `source_dataset` | `text` | no | HistAI subset, for example `HISTAI-breast`. |
| `source_case_id` | `text` | no | The `case_<id>` value from HistAI. |
| `specialty` | `text` | no | `breast`, `thorax`, `colorectal`, `gastrointestinal`, `hematologic` or `skin`. |
| `patient_age` | `integer` | yes | Years, from HistAI `age`. |
| `patient_sex` | `text` | yes | `F` or `M`, from HistAI `gender`. |
| `icd10` | `text` | yes | ICD-10 code. Null for held-out cases in anything sent to the client. |
| `status` | `text` | no | `open` (not reported) or `signed_out`. |
| `assigned_to` | `text` FK | no | The pathologist responsible. For signed-out cases, the report author. |
| `accessioned_at` | `timestamptz` | no | When the case arrived. Orders the worklist (F-01.1). |
| `is_held_out` | `boolean` | no | True for cases whose real report is hidden for evaluation (F-09.2). |
| `cohort_tier` | `text` | no | `smoke`, `demo` or `stretch`. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `assigned_to` → `pathologist.id`.
- Has many `slide`; has zero or one `report`; has many `consult_thread`.

## Indexes
- `(status, assigned_to, accessioned_at desc)` — My cases.
- `(specialty, accessioned_at desc)` — filtered worklist.
- `(icd10 text_pattern_ops)` — ICD-10 prefix filter.
- Unique `(source_dataset, source_case_id)`.

## Rules
1. `status = 'open'` exactly when `is_held_out` is true. In the hackathon data, the only open cases are held-out ones.
2. A signed-out case has a report with `status = 'signed'` and `assigned_to = report.author_id`.
3. Open cases are assigned across the roster by specialty, with the demo user receiving at least three.
4. `icd10` of a held-out case is stored but never sent to the client.

## Source
`source_*`, `specialty`, `patient_age`, `patient_sex`, `icd10` come from HistAI metadata; `specialty` falls back to the subset name when the metadata field is empty. `assigned_to` and `accessioned_at` are synthetic: dates are spread over the 90 days before the hackathon, deterministically from the case ID.

## API shape
`CaseSummary` — `id`, `specialty`, `patient_age`, `patient_sex`, `icd10`, `status`, `assigned_to` as `PathologistRef`, `accessioned_at`, `slide_count`, `thumbnail_url`, `conclusion_line`. For an open case `icd10` and `conclusion_line` are null.

`CaseDetail` — `CaseSummary` plus `slides` (list of `SlideSummary`) and `report_status`.

Never sent: `is_held_out` (the client sees only `status`), `source_*`, `cohort_tier`.
