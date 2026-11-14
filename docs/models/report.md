---
model: report
table: report
status: planned
written_by: pipeline
used_by: [F-01, F-02, F-04, F-05, F-07, F-10]
---

# report

## Purpose
The pathology report of a case: the full cleaned OCR text from `TCGA-Reports` plus best-effort extracted sections and synthetic authorship. A signed report is what gives a retrieved slide region its meaning.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | `{case_id}-r1`. |
| `case_id` | `text` FK, unique | no | One report per case. |
| `author_id` | `text` FK | no | The pathologist who reported it. Drives the consult ranking (F-07.4). |
| `status` | `text` | no | `signed`, `withheld` (real report hidden; case appears open) or `draft` (reserved for F-11). |
| `body` | `text` | no | Full cleaned OCR report text from `TCGA-Reports`. Never sent for a withheld report. |
| `clinical_history` | `text` | yes | Extracted incoming clinical notes, when a heading is present. The only section shown for an open case (F-04.3). |
| `gross_description` | `text` | yes | Extracted macroscopic examination, when a heading is present. |
| `microscopic_description` | `text` | yes | Extracted microscopic examination, when a heading is present. |
| `conclusion` | `text` | yes | Extracted pathological diagnosis / conclusion section, when a heading is present. |
| `additional_info` | `text` | yes | Extracted comment, note or synoptic section, when a heading is present. |
| `icd10` | `text` | yes | ICD-10 code from GDC clinical data. |
| `signed_at` | `timestamptz` | yes | Sign-out time. Null unless signed. |
| `search_tsv` | `tsvector`, generated | no | English text-search vector: `conclusion` weighted A, `microscopic_description` and `additional_info` B, `gross_description`, `clinical_history` and `body` C. |
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
1. Every query that returns report text to a client filters `status = 'signed'`. For a withheld report only `clinical_history` may be returned (`body` and all other sections are withheld).
2. A withheld report still has its real `body`, extracted sections, `icd10` and `author_id` stored, for evaluation only (F-10.6).
3. Every report has a non-empty `body`. Extracted section columns may be null when a hospital report lacks standard headings.
4. Extracted sections hold trimmed spans of `body`, with empty strings stored as null. `clinical_history` extraction stops strictly at the first specimen, gross, microscopic or diagnosis heading so diagnostic conclusions never leak into an open held-out case.

## Source
`body` comes from the `text` column of `TCGA_Reports.csv`, joined to the case by the 12-character patient barcode (`patient_filename[:12] = path_case.source_case_id`). Section columns are extracted best-effort by hospital heading patterns:

| Field | Heading patterns matched in `body` |
| --- | --- |
| `clinical_history` | `Clinical History`, `Clinical Diagnosis & History`, `Clinical Information`, `Preoperative Diagnosis` |
| `gross_description` | `Gross Description`, `Macroscopic Description`, `Gross Examination` |
| `microscopic_description` | `Microscopic Description`, `Microscopic Examination` |
| `conclusion` | `Final Diagnosis`, `Pathologic Diagnosis`, `Diagnosis`, `Conclusion`, `Interpretation` |
| `additional_info` | `Comment`, `Comments`, `Note`, `Synoptic Report`, `Addendum` |

`icd10` comes from GDC `diagnoses.icd_10_code`. `author_id` and `signed_at` are synthetic. Authors are assigned by specialty with a skew (F-09.6); `signed_at` is a few days after the case's `accessioned_at`.

## API shape
`Report` — `id`, `case_id`, `status`, `body`, the five extracted text sections (`clinical_history`, `gross_description`, `microscopic_description`, `conclusion`, `additional_info`), `icd10`, `signed_at`, `author` as `PathologistRef`, `is_synthetic_author: true`.

`ReportNotReported` — `case_id`, `status: "none"`, `clinical_history`. Returned for open cases.

Never sent: `search_tsv`; `body`, `icd10` or any section other than `clinical_history` of a withheld report; the value `withheld` itself.
