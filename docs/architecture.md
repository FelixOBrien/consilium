# Architecture

How Consilium is built, the decisions already made, and what could go wrong. Features are in [features/](features/index.md); the schema is in [models/](models/index.md).

## Shape

Embeddings are computed once, offline, on a GPU. Everything the user does at query time runs on CPU against Postgres.

```
 OFFLINE (rented GPU)                         ONLINE (laptop or Databricks App)

 TCGA: GDC API + TCGA-Reports CSV            SvelteKit SPA  (OpenSeadragon viewer)
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
| API | `python/src/consilium/api` | FastAPI. Patients, cases, reports, tiles, search, heatmaps, annotations, consult, ingestion jobs. Serves the built SPA in deployment. | <!-- pragma: allowlist secret -->
| Search | `consilium/search` | SQL for vector, keyword and fused retrieval. | <!-- pragma: allowlist secret -->
| Encoders | `consilium/embed` | CONCH-Z text tower and bge-small, loaded lazily, on CPU. | <!-- pragma: allowlist secret -->
| Tile server | `consilium/tiles` | Deep Zoom tiles from the original Aperio SVS file using `openslide-python` with the `openslide-bin` wheel, so no system packages are needed. Patch thumbnails from per-slide packs. | <!-- pragma: allowlist secret -->
| Consult agent | `consilium/agent` | Claude tool-use loop over the search functions, streamed to the UI. | <!-- pragma: allowlist secret -->
| Pipeline | `consilium/pipeline` | Cohort manifest, download, TRIDENT wrapper, projection, report processing, parquet export, loader, single-slide worker. | <!-- pragma: allowlist secret -->
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
| D7 | Serve tiles **dynamically from the original SVS**; no pre-cut tile pyramids. | Pre-cut pyramids are millions of small files per cohort, too slow to upload. One file per slide is cached on demand. | Pre-generated Deep Zoom directories. |
| D8 | **Patch thumbnails in one pack file per slide**, addressed by offset and length on the patch row. | Search results show patches from many slides at once; fetching every slide to cut one thumbnail is too slow. | Reading thumbnails from slides at query time; one file per thumbnail. |
| D9 | Heatmaps are computed **on demand**: encode the phrase, score the open slide's patches in SQL, min-max normalise per slide. Optional negative phrase subtracted. | A slide has a few thousand patches, so an exact scan is milliseconds. No precomputed concept tables. | Precomputing scores for a fixed concept list. |
| D10 | A region query is the **mean of stored vectors** for patches intersecting the region. | No vision model at query time, so no GPU in the app. | Live image encoding. |
| D11 | The agent is a **plain Anthropic SDK tool-use loop**, streamed over SSE. Model set by `ANTHROPIC_MODEL`. | Smallest moving part; full control of tool results and citations. Implementers read the current Claude API reference before writing the loop. | A heavier agent framework. |
| D12 | **Ingestion uses a pull queue.** The UI inserts an `ingestion_job` row; a worker on the GPU machine polls for queued jobs and writes results itself. | Works whatever the App's outbound network rules are, and reuses the bulk pipeline code. | The App calling a GPU endpoint directly. |
| D13 | **Synthetic pathologists**, assigned to reports by specialty with a deliberate skew. | TCGA reports have no authors, and the consult feature needs a clear, checkable answer. | Leaving authorship out. |
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
| Patients | `GET /patients`, `GET /patients/{id}` |
| Cases | `GET /cases`, `GET /cases/{id}`, `GET /cases/{id}/report`, `GET /cases/{id}/similar` |
| Slides | `GET /slides/{id}`, `GET /slides/{id}.dzi`, `GET /slides/{id}_files/{level}/{col}_{row}.jpeg`, `GET /slides/{id}/thumbnail`, `GET /slides/{id}/patches/at` |
| Patches | `GET /patches/{id}`, `GET /patches/{id}/thumbnail` |
| Search | `POST /search/reports`, `POST /search/patches` |
| Heatmap | `GET /concepts`, `POST /slides/{id}/heatmap` |
| Annotations | `GET`/`POST /slides/{id}/annotations`, `PATCH`/`DELETE /annotations/{id}` |
| Consult | `POST /cases/{id}/consult/threads`, `GET /consult/threads/{id}`, `POST /consult/threads/{id}/messages` |
| Ingestion | `POST /ingestion/jobs`, `GET /ingestion/jobs`, `GET /ingestion/jobs/{id}` |
| System | `GET /health` |

`POST /api/slides/{id}/heatmap` follows [F-06](features/F06-phrase-heatmaps.md). The request field `text` is the selected report word. The response lists every patch as `x`, `y`, `size` and `score` (min-max normalised to 0–1), the highest scores in `top`, and a `notice` that the shading is embedding similarity, not a finding. A client may send `concept_id` instead of `text` (exactly one of the two) and may send optional `negative_text` with either, so a stored phrase or the contrasting phrase from D9 stays available. `GET /api/concepts` returns [concept](models/concept.md) rows (`id`, `label`, `prompt`, `specialty`) and never returns embeddings.

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
| `HF_TOKEN` | secret | Gated CONCH-Z and CONCH v1.5 weights. TCGA slides and reports need no token. |
| `DATABRICKS_HOST`, `DATABRICKS_TOKEN` | secret | Volume access and deployment from outside Databricks. A trailing slash on the host is removed. |
| `DATABRICKS_VOLUME_ROOT` | `/Volumes/...` | Unity Catalog Volume that receives parquet, thumbnail packs, and slides. |
| `DATABRICKS_WAREHOUSE_ID` | warehouse id | Optional. Lets `consilium.pipeline reconcile` count Delta gold tables. | <!-- pragma: allowlist secret -->
| `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` | names | Optional Unity Catalog names for those gold counts. |
| `MLFLOW_TRACING_ENABLED` | `true` \| `false` | Log each consult turn as an MLflow trace. Default `false`: the agent does not import MLflow and does not call Databricks. |
| `MLFLOW_EXPERIMENT_NAME` | path | Experiment for those traces. Default `/Shared/consilium-consult`. | <!-- pragma: allowlist secret -->
| `MLFLOW_TRACKING_URI` | `databricks` or a directory | Where traces go. Unset means `databricks`, using `DATABRICKS_HOST` and `DATABRICKS_TOKEN`. A local directory is the file store used in tests. Tracing stays off when the Databricks target is selected and either credential is missing. |

## Data layout

```
data/                              # local, git-ignored; mirrored under the Volume root
  cohort/cohort.csv                # manifest: case, slide, GDC file id, project, tier, held_out
  source/TCGA_Reports.csv          # TCGA-Reports, unzipped
  source/gdc_cases.parquet         # GDC clinical fields for the candidate cases
  slides/{slide_id}.svs            # original Aperio SVS from the GDC
  trident/                         # TRIDENT job dir: coords and raw features (H5)
  thumbs/{slide_id}.pack           # concatenated patch JPEGs
  export/*.parquet                 # pathologist, patient, path_case, slide, report, report_chunk, concept, patch
```

Delta tables mirror the parquet files: `bronze` as landed, `silver` typed and deduplicated, `gold` joined for serving. Lakebase is loaded from gold.

## Risks

| Risk | Likelihood | Response |
| --- | --- | --- |
| Slide download or feature extraction overruns the evening (TCGA slides are 0.2–2 GB each) | Medium | Cap slide size at 1 GB in the manifest, download with bounded parallelism ahead of extraction, start the smoke test first, and cut the cohort tier rather than features if needed. |
| An SVS file lacks `aperio.MPP` or `aperio.AppMag`, so TRIDENT cannot find 20x | Low | Caught by the smoke test. Supply microns-per-pixel in TRIDENT's slide list, or drop the slide from the manifest. |
| Lakebase Free Edition storage or index build cannot hold the demo tier | Medium | Load the measured subset below. The full tier stays in local Postgres. Delta gold still matches the full parquet. |
| The App cannot reach the Anthropic API | Medium | Test in the provisioning issue. Fall back to `LLM_PROVIDER=databricks`, or run the API on the laptop against Lakebase. |
| Databricks App deployment fails late | Medium | Laptop run is the default demo path; the App is an addition. |
| CONCH-Z text tower is slow or large on CPU | Low | Cache encoded queries; the concept chips are pre-encoded at startup. |
| Text-to-patch results are weak for some phrases | Medium | Curate the demo concepts and cases from what the evaluation shows works. |
| Agent spends the credit budget | Low | Cap tool-result size and turn count; use a mid-tier model. |

### Lakebase subset

Lakebase Free Edition caps a project at 512 MB (`neon.max_cluster_size`). The demo tier's patch vectors alone are larger than that, so Lakebase does not receive the full export. `SEARCH_BACKEND` stays `pgvector`. Migrations create the HNSW and GIN indexes in `0002_indexes.sql` and never create `lakebase_ann` or `lakebase_bm25`.

Measured on 14 Nov 2026 with Postgres 16.15 and pgvector 0.8.7, the same extension version as this Lakebase project: 4,000 `patch` rows, 3,200 of them `in_corpus`. `pg_relation_size(patch)` was 8,192,000 bytes (2,048 per row). The partial HNSW index was 6,561,792 bytes (2,051 per in-corpus row). Report-chunk embeddings are the same 1,536-byte payload, so they use the same constants.

The selector adds 25% headroom (5,124 bytes for an in-corpus patch, chunk, or ready slide; 2,560 bytes otherwise), keeps 32 MiB for the rest of the catalog, and stops sampling once the estimate reaches 320 MiB. That sits inside the 250–350 MiB band and leaves the rest of the 512 MB cap unused. Held-out open cases are always kept, and so is every earlier case of a patient who is included. Every pathologist and every concept is copied. Signed-out cases fill the remaining slots one specialty at a time, in specialty order, up to `--max-cases` (default 45). The command is:

```bash
uv run python -m consilium.pipeline subset --from data/export --out data/export_lakebase --max-cases 45 <!-- pragma: allowlist secret -->
SEARCH_BACKEND=pgvector uv run python -m consilium.pipeline load --from data/export_lakebase <!-- pragma: allowlist secret -->
```

`load` logs `pg_database_size(current_database())` after the copy and the index build. `consilium.pipeline reconcile --from data/export --subset-from data/export_lakebase` expects Delta gold to match the full parquet and Postgres to match the subset. <!-- pragma: allowlist secret -->
