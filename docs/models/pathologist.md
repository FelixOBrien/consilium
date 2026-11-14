---
model: pathologist
table: pathologist
status: planned
written_by: pipeline
used_by: [F-01, F-04, F-07, F-08]
---

# pathologist

## Purpose
A member of the synthetic roster. A pathologist is both a report author, which the consult agent ranks, and an identity the app user can act as.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | Slug, for example `path-okafor`. |
| `name` | `text` | no | Display name with title, for example "Dr A. Okafor". |
| `role_title` | `text` | no | For example "Consultant Histopathologist". |
| `primary_specialty` | `text` | no | The specialty they report most. One of the `path_case.specialty` values. |
| `secondary_specialties` | `text[]` | no | Other specialties they sometimes report. May be empty. |
| `is_demo_user` | `boolean` | no | True for the identity used when none is chosen (F-01.7). Exactly one row. |
| `is_synthetic` | `boolean` | no | Always true. Kept so every consumer can label the data. |
| `created_at` | `timestamptz` | no | |

## Relationships
- Referenced by `path_case.assigned_to`, `report.author_id`, `annotation.author_id`, `consult_thread.user_id`, `ingestion_job.requested_by`.

## Indexes
- Primary key only. The table has about 12 rows.

## Rules
1. About 12 rows: two per specialty, with secondary specialties overlapping so that some pathologists report across organs.
2. Exactly one row has `is_demo_user = true`.
3. Names are invented and must not be those of real, identifiable pathologists.

## Source
Seeded from a file in the repository at pipeline stage 7. Entirely synthetic: HistAI has no author information ([context.md](../context.md#what-the-dataset-does-not-have)).

## API shape
`Pathologist` — all fields. `PathologistRef` — `id`, `name`, `primary_specialty`, `is_synthetic`, embedded in cases, reports and annotations.
