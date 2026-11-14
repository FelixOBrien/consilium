---
model: concept
table: concept
status: planned
written_by: pipeline
used_by: [F-06]
---

# concept

## Purpose
A curated histological phrase offered as a one-click heatmap, with the wording that works well for the text encoder and an optional contrasting phrase.

## Fields

| Field | Type | Null | Description |
| --- | --- | --- | --- |
| `id` | `text` PK | no | Slug, for example `tumour-necrosis`. |
| `label` | `text` | no | Short name shown on the chip. |
| `prompt` | `text` | no | The phrase encoded for the heatmap, for example "an H&E image of tumour necrosis". |
| `negative_prompt` | `text` | yes | A contrasting phrase whose similarity is subtracted (F-06.2), for example "normal tissue". |
| `specialty` | `text` | yes | The specialty the concept applies to. Null means general (F-06.7). |
| `ordinal` | `integer` | no | Display order. |
| `embedding` | `halfvec(768)` | yes | Encoded `prompt`, `conchz` space. |
| `negative_embedding` | `halfvec(768)` | yes | Encoded `negative_prompt`. |
| `created_at` | `timestamptz` | no | |

## Relationships
None.

## Indexes
- Primary key only. A few dozen rows.

## Rules
1. Prompts are under the encoder's 127-token limit.
2. Embeddings are filled when the list is loaded, so clicking a chip needs no text encoding at request time.
3. A concept stays in the list only if it gives a sensible map on at least one demo case (F-06 open question).

## Source
A file of concepts in the repository, loaded and encoded by the pipeline. Start with about 20: general ones such as necrosis, mitotic figures, lymphocytic infiltrate, fibrosis, mucin, glandular differentiation, keratinisation, haemorrhage, plus a few per specialty.

## API shape
`Concept` — `id`, `label`, `prompt`, `specialty`.

Never sent: the embeddings.
