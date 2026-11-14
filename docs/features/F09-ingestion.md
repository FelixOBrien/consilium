---
id: F-09
title: Ingestion
status: planned
priority: P0
stories: [US-09.1, US-09.2, US-09.3, US-09.4]
models: [ingestion_job, patient, case, slide, patch, report, report_chunk, pathologist]
screens: [S-08]
depends_on: []
linear: [SKO-257, SKO-260, SKO-261, SKO-263, SKO-269, SKO-272, SKO-273, SKO-280, SKO-284]
---

# F-09 · Ingestion

## Summary
Slides and reports go from TCGA (NCI Genomic Data Commons diagnostic slides paired with `TCGA-Reports` CSV text) to searchable rows. A data operator runs the pipeline in bulk for a cohort, and can queue a single new slide and watch it become searchable.

Bulk ingestion is P0: nothing else works without data. Queuing a single slide from the UI is P2.

## Why
All goals depend on it. Running a real ingestion in front of judges also shows the system is a pipeline, not a static demo.

## Scope
**In**
- Building a cohort manifest by joining GDC diagnostic slide and clinical metadata with `TCGA-Reports`.
- Slide download from the GDC API, tissue segmentation, patching, embedding, projection, thumbnails.
- Report text cleaning and best-effort section extraction, synthetic authorship, chunking, embedding.
- Export to parquet, load into Postgres, index.
- The Databricks path: Volume, Delta tables, Lakebase.
- A job queue for single slides.

**Out**
- Uploading a slide file through the browser. A single-slide job references a TCGA project and GDC slide file name or file ID.
- De-identification. TCGA open-access slides and `TCGA-Reports` are already public and de-identified.
- Frozen-section slides (`TS`/`BS` barcodes) and stains other than diagnostic FFPE H&E (`DX` slides).

## Stages

| # | Stage | Input | Output |
| --- | --- | --- | --- |
| 1 | Manifest | GDC `files` + `cases` APIs, `TCGA_Reports.csv` | `cohort.csv` (one row per slide with case, GDC `file_id`, project, specialty, tier, `held_out`) and `source/gdc_cases.parquet` |
| 2 | Download | manifest | `slides/{slide_id}.svs` |
| 3 | Segment and patch | slide | tissue mask, patch coordinates (512 px at 20x effective magnification, no overlap) |
| 4 | Embed | patches | raw `conch_v15` features (TRIDENT H5) |
| 5 | Project | raw features | 768-d CONCH-Z vectors, L2-normalised; slide vector as the normalised mean |
| 6 | Thumbnails | slide, coordinates | `thumbs/{slide_id}.pack` and each patch's offset and length |
| 7 | Reports | `TCGA_Reports.csv`, `gdc_cases.parquet` | `patient` records (including multi-case longitudinal history), full report `body` + best-effort extracted sections, synthetic author and dates, chunks with 384-d vectors |
| 8 | Export | all above | parquet files, one per table |
| 9 | Load | parquet | Postgres rows, then vector and text indexes |
| 10 | Lakehouse | parquet in a Volume | Delta bronze, silver, gold; Lakebase loaded from gold |

## Behaviour
1. The manifest builder queries open-access TCGA `Diagnostic Slide` SVS files in the target projects (`BRCA`, `LUAD`, `LUSC`, `COAD`, `READ`, `STAD`, `ESCA`, `SKCM`, `DLBC`), joins them to GDC `cases` clinical data and `TCGA_Reports.csv` on the 12-character patient barcode (`submitter_id`), drops slides over the size cap (default 1 GB) or cases missing report text or a primary GDC diagnosis, keeps one slide per case (preferring `DX1`, then smallest file size), maps TCGA project to `specialty`, and samples an equal number of cases per specialty for the requested tier (taking all available where a specialty such as `hematologic` has fewer). Sampling uses a fixed seed.
2. The manifest marks about 10 cases in the demo tier (2 in smoke), spread across specialties, as `held_out`, preferring candidates whose report has an extractable `clinical_history` section without diagnostic leakage. They load as open cases with `report.status = withheld`.
3. Stages 2 to 6 are per slide, idempotent and resumable: a slide whose outputs exist is skipped, and a failed slide is recorded and does not stop the run.
4. Patch vectors are stored only after projection ([architecture D2](../architecture.md#decisions)).
5. Report text from `TCGA_Reports.csv` is stored in full in `report.body` and split best-effort by hospital section headings into `clinical_history`, `gross_description`, `microscopic_description`, `conclusion` and `additional_info` ([report](../models/report.md#source)). Clinical fields (`primary_diagnosis`, ICD-O-3 `morphology`, `icd10`, `patient_age`, `patient_sex`) come from GDC `cases`.
6. Stage 7 builds `patient` rows ([patient](../models/patient.md#source)): distinct specimens from the same TCGA donor share one `patient` (`is_synthetic_linkage = false`), and about 15–20% of cohort cases (including at least three held-out demo cases) are deterministically paired into longitudinal 2–3 case histories matching sex and clinical trajectory (`is_synthetic_linkage = true`, prior signed-out cases dated 3–24 months earlier). Each report is assigned a synthetic author from the roster, deterministic and skewed so that within a specialty one pathologist has reported clearly more cases than the others, and a few report outside their main specialty.
7. Reports are chunked by partitioning `body` along detected section boundaries (using `section = 'body'` where no heading matched) and splitting spans over ~200 words on sentence boundaries with one sentence of overlap. Each chunk records its section.
8. Indexes are built after rows are loaded.
9. The loader is safe to re-run: it replaces the rows for the slides and cases in the parquet files it is given.
10. A single-slide job is created with a TCGA project (`dataset`, for example `TCGA-BRCA`) and a GDC slide file name or file ID (`slide_path`). A worker on the GPU machine polls for queued jobs, resolves metadata from GDC and `TCGA_Reports.csv`, runs stages 2 to 9 for that slide, and updates the job's stage and status as it goes.
11. A job that fails records the stage and error, and can be retried.
12. A slide becomes searchable when its job reaches `done`; until then its case shows the slide's ingestion status.
13. The run prints, and the job stores, counts per stage: slides, patches, reports, chunks, failures.

## API
- `POST /api/ingestion/jobs` — body: `dataset` (TCGA project ID), `slide_path` (GDC slide file name or file ID). Creates a queued job.
- `GET /api/ingestion/jobs` — recent jobs with stage and status.
- `GET /api/ingestion/jobs/{id}` — one job with stage history and counts.

The pipeline itself is a command-line program in `consilium.pipeline`, one subcommand per stage and one that runs them in order. <!-- pragma: allowlist secret -->

## Acceptance
- The smoke tier (10 slides) runs end to end on one machine and the cases appear in the worklist with working slides and search.
- Re-running the pipeline on the same manifest does no repeated work and creates no duplicate rows.
- The demo tier is loaded locally and in Lakebase, with row counts that match between parquet, Delta gold and Postgres.
- A queued single-slide job moves through its stages and the slide becomes searchable without restarting the API.

## Open questions
- A few TCGA `.svs` files have no resolution metadata (see [F-03](F03-slide-viewer.md)). Stage 4 records those slides and continues; it does not invent a microns-per-pixel value.
- Lakebase Free Edition stores at most 512 MB ([context](../context.md#platform-databricks-free-edition)), which caps the tier loaded there. The manifest tiers are the subset that load can choose.
