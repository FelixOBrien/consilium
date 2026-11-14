---
model: report_chunk
table: report_chunk
status: planned
written_by: pipeline
used_by: [F-02, F-05, F-07]
---

# report_chunk

## Purpose
A passage of a report with its text embedding. Semantic report search matches chunks, then reports results by case with the best passage.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `bigint` PK, identity | no | |
| `report_id` | `text` FK | no | |
| `case_id` | `text` FK | no | Copied from the report so results group by case without a join. |
| `patient_id` | `text` FK | no | Copied from the case so patient-scoped report search filters inside the vector query (F-12.4). |
| `specialty` | `text` | no | Copied from the case, for filtering inside the vector search. |
| `section` | `text` | no | Which report span the text is from: `clinical_history`, `gross_description`, `microscopic_description`, `conclusion`, `additional_info` or `body` (for unsectioned text or text outside recognised headings). |
| `ordinal` | `integer` | no | Order of the chunk within the report. |
| `text` | `text` | no | The passage. Shown as the matching passage in results (F-05.5). |
| `embedding` | `vector(384)` | no | bge-small-en-v1.5 embedding, L2-normalised, `report` space. |
| `in_corpus` | `boolean` | no | True when the chunk may be returned as precedent. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `report_id` → `report.id`, `case_id` → `path_case.id`. Deleting a report deletes its chunks.

## Indexes
- HNSW on `embedding` with `vector_cosine_ops`, partial on `in_corpus`.
- `(report_id, ordinal)` unique.
- `(patient_id)` — patient-scoped semantic search across a patient's signed-out reports (F-12.4).

## Rules
1. `report.body` is partitioned at detected section headings into contiguous `(section, text)` spans so every word of the report is indexed once (`section = 'body'` where no heading matched). Spans over about 200 words are split on sentence boundaries with one sentence of overlap.
2. `in_corpus` is true exactly when the report is signed and its case is not held out. Chunks of withheld reports are stored with `in_corpus = false`.
3. `clinical_history` chunks are stored but excluded from precedent search by default, since they describe the question rather than the answer; the search may include them by section filter.
4. Chunks are embedded as passages. Queries are embedded with the model's query instruction prefix.

## Source
Pipeline stage 7, from partitioning `report.body` along extracted section boundaries.

## API shape
Not sent as a list. A matching chunk appears inside a search result as `Passage` — `section`, `text`, `highlights` (see [search_hit](search_hit.md)).

Never sent: `embedding`, `in_corpus`.
