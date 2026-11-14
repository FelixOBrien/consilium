---
model: patch
table: patch
status: planned
written_by: pipeline
used_by: [F-02, F-03, F-05, F-06, F-10]
---

# patch

## Purpose
One square tile of tissue from a slide, with the vector that represents what it looks like. Patches are what tissue search and heatmaps operate on. This is the largest table.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `bigint` PK, identity | no | |
| `slide_id` | `text` FK | no | |
| `case_id` | `text` FK | no | Copied from the slide so results group by case without a join. |
| `patient_id` | `text` FK | no | Copied from the case so patient-scoped tissue search filters inside the vector query (F-12.4). |
| `specialty` | `text` | no | Copied from the case so the specialty filter applies inside the vector search (F-05.7). |
| `x` | `integer` | no | Left edge, level-0 pixels. |
| `y` | `integer` | no | Top edge, level-0 pixels. |
| `size` | `integer` | no | Side length, level-0 pixels. Equals `slide.patch_size`. |
| `embedding` | `halfvec(768)` | no | CONCH-Z projected image embedding, L2-normalised, `conchz` space. |
| `in_corpus` | `boolean` | no | True when the patch may be returned as precedent (F-05.1). |
| `thumb_offset` | `bigint` | no | Byte offset of this patch's JPEG in the slide's thumbnail pack. |
| `thumb_length` | `integer` | no | Byte length of that JPEG. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `slide_id` → `slide.id`, `case_id` → `path_case.id`. Deleting a slide deletes its patches.

## Indexes
- HNSW on `embedding` with `halfvec_cosine_ops`, partial on `in_corpus` — corpus search (Q1, Q2, Q4).
- `(slide_id, x, y)` unique — hit-testing a click (F-03.6), the region query (Q2), and heatmaps, which scan one slide exactly.
- `(case_id)` — grouping and exclusion of the context case.
- `(patient_id)` — patient-scoped tissue search across a patient's signed-out cases (F-12.4).

With `SEARCH_BACKEND=lakebase` the HNSW index is replaced by a `lakebase_ann` index on the same column.

## Rules
1. Patches are 512 px at 20x effective magnification with no overlap, on tissue only (`size` in level-0 pixels equals `slide.patch_size`: 512 on a 20x slide, 1024 on a 40x slide). Positions are multiples of `size` offset from the slide's patching origin.
2. `embedding` is stored after CONCH-Z projection and normalisation, never raw ([architecture D2](../architecture.md#decisions)).
3. `in_corpus` is true exactly when the case is signed out and not held out.
4. `patient_id`, `specialty` and `case_id` always equal the values on the owning slide's case.
5. Built after load: rows first, vector index second (F-09.8).

## Source
Coordinates from pipeline stage 3, embeddings from stages 4 and 5, thumbnail offsets from stage 6.

Sizing for planning: about 3,000 patches per slide. The demo tier is about 600,000 rows; at 768 half-precision dimensions that is roughly 0.9 GB of vectors before the index.

## API shape
`PatchRef` — `id`, `slide_id`, `case_id`, `x`, `y`, `size`, `thumbnail_url`.

Never sent: `embedding`, `thumb_offset`, `thumb_length`, `in_corpus`.
