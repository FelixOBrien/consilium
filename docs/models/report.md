---
model: report
table: report
status: planned
written_by: pipeline
used_by: [F-01, F-02, F-04, F-05, F-07, F-10]
---

# report

## Purpose
The pathology report of a case, held in the sections a report is written in, with its author. A signed report is what gives a retrieved slide region its meaning.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | `{case_id}-r1`. |
| `case_id` | `text` FK, unique | no | One report per case. |
| `author_id` | `text` FK | no | The pathologist who reported it. Drives the consult ranking (F-07.4). |
| `status` | `text` | no | `signed`, `withheld` (real report hidden; case appears open) or `draft` (reserved for F-11). |
| `clinical_history` | `text` | yes | Incoming clinical notes. The only section shown for an open case (F-04.3). |
| `gross_description` | `text` | yes | Macroscopic examination. |
| `microscopic_description` | `text` | yes | What was seen on the slides. |
| `conclusion` | `text` | yes | The final pathological diagnosis. |
| `differential` | `text` | yes | Differential diagnosis notes. |
| `additional_info` | `text` | yes | Supplementary notes. |
| `icd10` | `text` | yes | Code assigned with the report. |
| `signed_at` | `timestamptz` | yes | Sign-out time. Null unless signed. |
| `search_tsv` | `tsvector`, generated | no | English text-search vector: conclusion weighted A, microscopic and differential B, the rest C. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `case_id` → `path_case.id`; `author_id` → `pathologist.id`.
- Has many `report_chunk`.

## Indexes
- GIN on `search_tsv` — keyword search (Q5).
- `(author_id)` — the consult ranking and the cases-by-author filter.
- `(status)`.

With `SEARCH_BACKEND=lakebase` a `lakebase_bm25` index on `search_tsv` replaces the GIN index for ranking; it is built after rows are loaded.

## Rules
1. Every query that returns report text to a client filters `status = 'signed'`. For a withheld report only `clinical_history` may be returned.
2. A withheld report still has its real sections and `author_id` stored, for evaluation only (F-10.6).
3. A signed report has a non-empty `conclusion`.
4. Sections hold text as HistAI provides it, trimmed, with empty strings stored as null.

## Source

| Field | HistAI field |
| --- | --- |
| `clinical_history` | `diagnosis` |
| `gross_description` | `grossing` |
| `microscopic_description` | `micro_protocol` |
| `conclusion` | `conclusion` |
| `differential` | `diff_diagnosis` |
| `additional_info` | `additional_info` |
| `icd10` | `icd10` |

`author_id` and `signed_at` are synthetic. Authors are assigned by specialty with a skew (F-09.6); `signed_at` is a few days after the case's `accessioned_at`.

## API shape
`Report` — `id`, `case_id`, `status`, the six text sections, `icd10`, `signed_at`, `author` as `PathologistRef`, `is_synthetic_author: true`.

`ReportNotReported` — `case_id`, `status: "none"`, `clinical_history`. Returned for open cases.

Never sent: `search_tsv`; any section other than `clinical_history` of a withheld report; the value `withheld` itself.
