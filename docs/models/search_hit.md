---
model: search_hit
table: none
status: planned
written_by: none
used_by: [F-02, F-05, F-07]
---

# search_hit

## Purpose
The shapes every search returns. Results are always cases, each carrying the evidence that matched: patches, a report passage, or both. The same shapes are returned to the UI and, trimmed, to the consult agent's tools.

## Fields

**`SearchResponse`**

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `query_kind` | `text` | no | `patch`, `region`, `slide`, `text_patches` or `reports` (F-05 Q1–Q5). |
| `hits` | list of `CaseHit` | no | Ordered best first. |
| `total_candidates` | `integer` | no | Patches or chunks considered before grouping. |
| `took_ms` | `integer` | no | Server time, for checking F-05.13. |
| `notice` | `text` | yes | For example, that the query text was truncated. |

**`CaseHit`**

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `case` | `CaseSummary` | no | See [case](case.md). Includes author through the report. |
| `author` | `PathologistRef` | no | The report's author. |
| `same_patient` | `boolean` | no | True when the hit case belongs to the same `patient_id` as `context_case_id` (F-05.6, F-12.6). |
| `score` | `real` | no | 0–1 relative score within this response; the top hit is 1. Not a probability (F-05.14). |
| `matched_by` | list of `text` | no | Any of `morphology`, `keyword`, `semantic`. |
| `patches` | list of `PatchHit` | no | Up to three. Empty for report-only matches. |
| `patch_match_count` | `integer` | no | How many of the candidate patches belonged to this case. |
| `passage` | `Passage` | yes | Best-matching report passage. Null for patch-only matches. |

**`PatchHit`**

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `patch_id` | `bigint` | no | |
| `slide_id` | `text` | no | |
| `x`, `y`, `size` | `integer` | no | Level-0 pixels, enough to build the viewer URL (F-03.5). |
| `similarity` | `real` | no | Cosine similarity to the query vector. |
| `thumbnail_url` | `text` | no | |

**`Passage`**

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `section` | `text` | no | Report section the text is from. |
| `text` | `text` | no | The chunk text. |
| `highlights` | list of `[start, end]` | no | Character ranges of matched keywords. Empty for a semantic-only match. |

**`SearchFilters`** (request)

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `patient_id` | `text` | yes | Restrict search to cases belonging to one patient (used by F-12.4 and the consult agent's patient search, F-07). |
| `specialty` | list of `text` | yes | |
| `icd10_prefix` | `text` | yes | |
| `stain` | `text` | yes | |
| `status` | `text` | yes | Global search only (F-02.6). Evidence search is always signed-out cases. |

## Relationships
Built from `patch`, `slide`, `report_chunk`, `report`, `path_case` and `pathologist`.

## Indexes
None.

## Rules
1. A response never contains the context case, an open case, or text from a withheld report.
2. `score` is normalised per response. `similarity` is the raw cosine value.
3. Hits are unique by case.
4. The agent's tools receive the same data with thumbnails dropped and passages cut to 400 characters (F-07.11).

## Source
Computed per request by `consilium.search`.

## API shape
These are the API shapes. Pydantic models carry the names above.
