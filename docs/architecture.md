# Architecture

How Consilium is built, the decisions already made, and what could go wrong. Features are in [features/](features/index.md); the schema is in [models/](models/index.md).

## Shape

Embeddings are computed once, offline, on a GPU. Everything the user does at query time runs on CPU against Postgres.

```
 OFFLINE (rented GPU)                         ONLINE (laptop or Databricks App)

 HistAI on Hugging Face                        SvelteKit SPA  (OpenSeadragon viewer)
        │ cohort manifest                             │  /api  (JSON, SSE, tiles)
        ▼                                             ▼
 download slides ──► TRIDENT                   FastAPI  ── consult agent ──► Claude API
                     segment · patch            │   │  │        │ tools
                     conch_v15 features         │   │  └────────┘
        │                                       │   └─ CONCH-Z text encoder (CPU)
        ▼                                       │      bge-small encoder (CPU)
 CONCH-Z projection ─► parquet + thumbnail      ▼
 report chunk + embed   packs + slides     Postgres + pgvector          slide + thumbnail store
        │                                  (Docker locally,             (local dir, or
        └────────── load ────────────────►  Lakebase on Databricks)      Unity Catalog Volume)
                      │
                      └─► Unity Catalog Volume ─► Delta bronze / silver / gold ─► Lakebase
```

## Components

| Component | Where | Responsibility |
| --- | --- | --- |
| Web app | `typescript/apps/web` | SvelteKit static SPA. Screens in [screens/](screens/index.md). Talks only to `/api`. |
| API | `python/src/consilium/api` | FastAPI. Cases, reports, tiles, search, heatmaps, annotations, consult, ingestion jobs. Serves the built SPA in deployment. |
| Search | `consilium/search` | SQL for vector, keyword and fused retrieval. |
| Encoders | `consilium/embed` | CONCH-Z text tower and bge-small, loaded lazily, on CPU. |
| Tile server | `consilium/tiles` | Deep Zoom tiles from the original pyramidal TIFF using `openslide-python` with the `openslide-bin` wheel, so no system packages are needed. Patch thumbnails from per-slide packs. |
| Consult agent | `consilium/agent` | Claude tool-use loop over the search functions, streamed to the UI. |
| Pipeline | `consilium/pipeline` | Cohort manifest, download, TRIDENT wrapper, projection, report processing, parquet export, loader, single-slide worker. |
| Lakehouse | `python/databricks` | Notebook that builds Delta tables from the Volume and loads Lakebase; App config. |

## Decisions

| # | Decision | Why | Rejected |
| --- | --- | --- | --- |
| D1 | **CONCH-Z** for patch embeddings and image-query text (768-d shared space). Vision features come from TRIDENT's `conch_v15` encoder (512 px patches at 20x, no overlap) and are passed through CONCH-Z `project_image_features`. | Text-to-patch search and phrase heatmaps work with no training. 512 px patches mean about a quarter of the patch count of 224 px tiling. Access is already approved. | **Virchow2**: vision-only, so text search needs a cross-attention probe trained on a thousand weakly paired slides, which is neither feasible before the freeze nor likely to generalise. 2,560-d vectors on four times the patches. |
| D2 | Store the **projected, L2-normalised** vector per patch. Raw `conch_v15` features stay on disk in TRIDENT's H5 output. | One vector serves patch-to-patch and text-to-patch. Skipping the projection breaks text alignment. | Storing raw features and projecting at query time. |
| D3 | A **second, separate embedding space** for reports: `BAAI/bge-small-en-v1.5`, 384-d, over report chunks. | CONCH-Z text is capped at 127 tokens and trained for image alignment, not document retrieval. A different dimension makes mixing the two spaces a hard error. | One space for everything; a hosted embedding API that may not be reachable from Free Edition. |
| D4 | **Postgres + pgvector is the storage and search contract.** Lakebase in deployment, Docker `pgvector` locally. HNSW on `halfvec` cosine; `tsvector` + GIN for keyword; reciprocal rank fusion in SQL. | Identical SQL in both places, so agents develop without Databricks access. | MongoDB Atlas (second system, reverse sync). Databricks Vector Search (one unit on Free Edition, no direct writes). |
| D5 | Lakebase Search index types are an **opt-in upgrade** behind `SEARCH_BACKEND`. | Enabling it is irreversible and its Free Edition behaviour is untested. | Depending on it from the start. |
| D6 | **Local first.** Storage, database and LLM provider are independent settings. | The demo is presented live; Apps cannot be public and stop after 24 hours. A laptop run against Lakebase is a full fallback. | Developing only against the deployed stack. |
| D7 | Serve tiles **dynamically from the original TIFF**; no pre-cut tile pyramids. | Pre-cut pyramids are millions of small files per cohort, too slow to upload. One file per slide is cached on demand. | Pre-generated Deep Zoom directories. |
| D8 | **Patch thumbnails in one pack file per slide**, addressed by offset and length on the patch row. | Search results show patches from many slides at once; fetching every slide to cut one thumbnail is too slow. | Reading thumbnails from slides at query time; one file per thumbnail. |
| D9 | Heatmaps are computed **on demand**: encode the phrase, score the open slide's patches in SQL, min-max normalise per slide. Optional negative phrase subtracted. | A slide has a few thousand patches, so an exact scan is milliseconds. No precomputed concept tables. | Precomputing scores for a fixed concept list. |
| D10 | A region query is the **mean of stored vectors** for patches intersecting the region. | No vision model at query time, so no GPU in the app. | Live image encoding. |
| D11 | The agent is a **plain Anthropic SDK tool-use loop**, streamed over SSE. Model set by `ANTHROPIC_MODEL`. | Smallest moving part; full control of tool results and citations. Implementers read the current Claude API reference before writing the loop. | A heavier agent framework. |
| D12 | **Ingestion uses a pull queue.** The UI inserts an `ingestion_job` row; a worker on the GPU machine polls for queued jobs and writes results itself. | Works whatever the App's outbound network rules are, and reuses the bulk pipeline code. | The App calling a GPU endpoint directly. |
| D13 | **Synthetic pathologists**, assigned to reports by specialty with a deliberate skew. | HistAI has no authors, and the consult feature needs a clear, checkable answer. | Leaving authorship out. |
| D14 | **No authentication.** The user picks an identity from the pathologist roster; the choice is sent as `X-User-Id`. | Public data, single-user demo. | Real auth. |
| D15 | **The OpenAPI schema is the frontend contract**; the TypeScript client is generated from it. | Lets API and UI issues proceed in parallel against one source of truth. | Hand-written types. |

## Request flows

**Open a case** — `GET /api/cases/{id}` returns the case with slides and report status. The viewer loads `/api/slides/{id}.dzi` and requests tiles as the user pans.

**Find similar tissue** — the user clicks a patch or draws a region. `POST /api/search/patches` with `patch_id` or `region` resolves a query vector from stored vectors, runs an HNSW search excluding the current case, and returns hits grouped by case with coordinates, thumbnail URL and report snippet.

**Describe tissue in words** — `POST /api/search/patches` with `text`. The API encodes it with the CONCH-Z text tower and runs the same search.

**Search reports** — `POST /api/search/reports`. Keyword rank from `tsvector`, semantic rank from chunk vectors, fused by reciprocal rank, grouped by case.

**Consult** — `POST /api/consult/threads/{id}/messages` streams. The agent calls search tools, reads reports, calls `rank_pathologists` for counts, and answers with citations.

## API surface

All routes are under `/api`. The exact shapes are the Pydantic models; each feature doc lists the routes it owns.

| Area | Routes |
| --- | --- |
| Identity | `GET /pathologists`, `GET /me` |
| Cases | `GET /cases`, `GET /cases/{id}`, `GET /cases/{id}/report`, `GET /cases/{id}/similar` |
| Slides | `GET /slides/{id}`, `GET /slides/{id}.dzi`, `GET /slides/{id}_files/{level}/{col}_{row}.jpeg`, `GET /slides/{id}/thumbnail`, `GET /slides/{id}/patches/at` |
| Patches | `GET /patches/{id}`, `GET /patches/{id}/thumbnail` |
| Search | `POST /search/reports`, `POST /search/patches` |
| Heatmap | `GET /concepts`, `POST /slides/{id}/heatmap` |
| Annotations | `GET`/`POST /slides/{id}/annotations`, `PATCH`/`DELETE /annotations/{id}` |
| Consult | `POST /cases/{id}/consult/threads`, `GET /consult/threads/{id}`, `POST /consult/threads/{id}/messages` |
| Ingestion | `POST /ingestion/jobs`, `GET /ingestion/jobs`, `GET /ingestion/jobs/{id}` |
| System | `GET /health` |

## Configuration

Environment variables, read through one settings module. `.env.example` lists them; real values never enter git.

| Variable | Values | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Postgres URL | Docker locally, Lakebase when deployed. |
| `STORAGE_BACKEND` | `local` \| `uc_volume` | Where slides and thumbnail packs are read from. |
| `STORAGE_ROOT` | path or `/Volumes/...` | Root of that store. |
| `SLIDE_CACHE_DIR`, `SLIDE_CACHE_MAX_GB` | path, number | On-disk cache of slides fetched from a Volume. |
| `SEARCH_BACKEND` | `pgvector` \| `lakebase` | Which index types the migrations and queries use. |
| `LLM_PROVIDER` | `anthropic` \| `databricks` | Where the agent's model calls go. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | secret, model id | Agent model. |
| `HF_TOKEN` | secret | Gated weights and dataset download. |
| `DATABRICKS_HOST`, `DATABRICKS_TOKEN` | secret | Volume access and deployment from outside Databricks. |

## Data layout

```
data/                              # local, git-ignored; mirrored under the Volume root
  cohort/cohort.csv                # manifest: case, slide, subset, tier, held_out
  slides/{slide_id}.tiff           # original pyramidal TIFF
  trident/                         # TRIDENT job dir: coords and raw features (H5)
  thumbs/{slide_id}.pack           # concatenated patch JPEGs
  export/*.parquet                 # pathologist, case, slide, report, report_chunk, patch
```

Delta tables mirror the parquet files: `bronze` as landed, `silver` typed and deduplicated, `gold` joined for serving. Lakebase is loaded from gold.

## Risks

| Risk | Likelihood | Response |
| --- | --- | --- |
| HistAI TIFFs lack resolution metadata, so TRIDENT cannot find 20x | Medium | Caught by the smoke test. Supply microns-per-pixel in TRIDENT's slide list (0.5 for 20x). |
| Download or extraction overruns the evening | Medium | Start the smoke test first and the full run as soon as it passes. Cut the cohort tier, not features. |
| Lakebase Free Edition storage or index build cannot hold the demo tier | Medium | Load a smaller tier into Lakebase; the full tier stays in local Postgres for the demo. |
| The App cannot reach the Anthropic API | Medium | Test in the provisioning issue. Fall back to `LLM_PROVIDER=databricks`, or run the API on the laptop against Lakebase. |
| Databricks App deployment fails late | Medium | Laptop run is the default demo path; the App is an addition. |
| CONCH-Z text tower is slow or large on CPU | Low | Cache encoded queries; the concept chips are pre-encoded at startup. |
| Text-to-patch results are weak for some phrases | Medium | Curate the demo concepts and cases from what the evaluation shows works. |
| Agent spends the credit budget | Low | Cap tool-result size and turn count; use a mid-tier model. |
