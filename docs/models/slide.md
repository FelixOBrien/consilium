---
model: slide
table: slide
status: planned
written_by: pipeline
used_by: [F-03, F-05, F-06, F-08, F-09, F-10]
---

# slide

## Purpose
One whole slide image belonging to a case: where its file is, its geometry, and one vector summarising its tissue.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | `{case_id}-s{ordinal}`, for example `breast-000412-s1`. |
| `case_id` | `text` FK | no | |
| `ordinal` | `integer` | no | Order within the case, from 1. |
| `stain` | `text` | no | `HE` for the hackathon cohort. |
| `magnification` | `real` | no | Objective power of level 0: 20 or 40. |
| `mpp` | `real` | no | Microns per pixel at level 0. Drives the scale bar (F-03.4). |
| `width` | `integer` | no | Level-0 width in pixels. |
| `height` | `integer` | no | Level-0 height in pixels. |
| `patch_size` | `integer` | no | Side of one patch in level-0 pixels: 512 on a 20x slide, 1024 on a 40x slide. |
| `patch_count` | `integer` | no | Number of tissue patches. |
| `storage_key` | `text` | no | Path of the image file under the storage root, `slides/{id}.tiff`. |
| `thumb_pack_key` | `text` | yes | Path of the patch thumbnail pack, `thumbs/{id}.pack`. |
| `source_path` | `text` | no | Path of the file within its HistAI repository. |
| `embedding` | `halfvec(768)` | yes | L2-normalised mean of the slide's patch embeddings, `conchz` space (F-05 Q3). |
| `status` | `text` | no | `pending`, `processing`, `ready` or `failed`. |
| `created_at` | `timestamptz` | no | |

## Relationships
- `case_id` → `path_case.id`.
- Has many `patch` and `annotation`.

## Indexes
- `(case_id, ordinal)` unique.
- HNSW on `embedding` with `halfvec_cosine_ops`, partial on `status = 'ready'`. With a few hundred rows an exact scan is also acceptable.

## Rules
1. `embedding` and `thumb_pack_key` are set exactly when `status = 'ready'`.
2. `mpp` and `magnification` come from the file when present, otherwise from the manifest: 0.5 and 20 for standard HistAI slides.
3. The file at `storage_key` is the original pyramidal TIFF; tiles are cut from it on request ([architecture D7](../architecture.md#decisions)).

## Source
Geometry is read from the file at pipeline stage 3. `embedding` is computed at stage 5. `status` is advanced by the pipeline or the worker.

## API shape
`SlideSummary` — `id`, `ordinal`, `stain`, `magnification`, `status`, `thumbnail_url`.

`SlideDetail` — adds `case_id`, `mpp`, `width`, `height`, `patch_size`, `patch_count`, `dzi_url`.

Never sent: `embedding`, `storage_key`, `thumb_pack_key`, `source_path`.
