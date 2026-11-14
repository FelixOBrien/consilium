---
id: F-09
title: Ingestion
status: planned
priority: P0
stories: [US-09.1, US-09.2, US-09.3, US-09.4]
models: [ingestion_job, case, slide, patch, report, report_chunk, pathologist]
screens: [S-08]
depends_on: []
linear: [SKO-257, SKO-260, SKO-261, SKO-263, SKO-269, SKO-272, SKO-273, SKO-280, SKO-284]
---

# F-09 · Ingestion

## Summary
Slides and reports go from the HistAI dataset to searchable rows. A data operator runs the pipeline in bulk for a cohort, and can queue a single new slide and watch it become searchable.

Bulk ingestion is P0: nothing else works without data. Queuing a single slide from the UI is P2.

## Why
All goals depend on it. Running a real ingestion in front of judges also shows the system is a pipeline, not a static demo.

## Scope
**In**
- Building a cohort manifest from HistAI metadata.
- Slide download, tissue segmentation, patching, embedding, projection, thumbnails.
- Report normalisation, synthetic authorship, chunking, embedding.
- Export to parquet, load into Postgres, index.
- The Databricks path: Volume, Delta tables, Lakebase.
- A job queue for single slides.

**Out**
- Uploading a slide file through the browser. A single-slide job references a slide by its HistAI path.
- De-identification. HistAI is already public and de-identified.
- Stains other than H&E and magnifications other than 20x.

## Stages

| # | Stage | Input | Output |
| --- | --- | --- | --- |
| 1 | Manifest | HistAI metadata | `cohort.csv`: one row per slide with case, subset, tier, `held_out` |
| 2 | Download | manifest | `slides/{slide_id}.tiff` |
| 3 | Segment and patch | slide | tissue mask, patch coordinates (512 px at 20x, no overlap) |
| 4 | Embed | patches | raw `conch_v15` features (TRIDENT H5) |
| 5 | Project | raw features | 768-d CONCH-Z vectors, L2-normalised; slide vector as the normalised mean |
| 6 | Thumbnails | slide, coordinates | `thumbs/{slide_id}.pack` and each patch's offset and length |
| 7 | Reports | metadata | normalised report sections, synthetic author and dates, chunks with 384-d vectors |
| 8 | Export | all above | parquet files, one per table |
| 9 | Load | parquet | Postgres rows, then vector and text indexes |
| 10 | Lakehouse | parquet in a Volume | Delta bronze, silver, gold; Lakebase loaded from gold |

## Behaviour
1. The manifest builder removes duplicate metadata entries, keeps H&E slides at 20x, drops cases whose `conclusion` is empty or molecular-only, takes one slide per case, and samples an equal number of cases per specialty for the requested tier. Sampling uses a fixed seed.
2. The manifest marks about 10 cases, spread across specialties, as `held_out`. They load as open cases with `report.status = withheld`.
3. Stages 2 to 6 are per slide, idempotent and resumable: a slide whose outputs exist is skipped, and a failed slide is recorded and does not stop the run.
4. Patch vectors are stored only after projection ([architecture D2](../architecture.md#decisions)).
5. Report text is normalised into sections by HistAI field: `diagnosis` to clinical history, `grossing` to gross description, `micro_protocol` to microscopic description, `conclusion`, `diff_diagnosis` to differential, `additional_info`.
6. Each report is assigned a synthetic author from the roster. Assignment is deterministic and skewed so that within a specialty one pathologist has reported clearly more cases than the others, and a few report outside their main specialty.
7. Reports are chunked by section, splitting long sections on sentence boundaries with overlap. Each chunk records its section.
8. Indexes are built after rows are loaded.
9. The loader is safe to re-run: it replaces the rows for the slides and cases in the parquet files it is given.
10. A single-slide job is created with a HistAI dataset and slide path. A worker on the GPU machine polls for queued jobs, runs stages 2 to 9 for that slide, and updates the job's stage and status as it goes.
11. A job that fails records the stage and error, and can be retried.
12. A slide becomes searchable when its job reaches `done`; until then its case shows the slide's ingestion status.
13. The run prints, and the job stores, counts per stage: slides, patches, reports, chunks, failures.

## API
- `POST /api/ingestion/jobs` — body: `dataset`, `slide_path`. Creates a queued job.
- `GET /api/ingestion/jobs` — recent jobs with stage and status.
- `GET /api/ingestion/jobs/{id}` — one job with stage history and counts.

The pipeline itself is a command-line program in `consilium.pipeline`, one subcommand per stage and one that runs them in order.

## Acceptance
- The smoke tier (10 slides) runs end to end on one machine and the cases appear in the worklist with working slides and search.
- Re-running the pipeline on the same manifest does no repeated work and creates no duplicate rows.
- The demo tier is loaded locally and in Lakebase, with row counts that match between parquet, Delta gold and Postgres.
- A queued single-slide job moves through its stages and the slide becomes searchable without restarting the API.

## Open questions
- Resolution metadata in HistAI files (see [F-03](F03-slide-viewer.md)).
- Lakebase storage available on Free Edition, which may cap the tier loaded there.
