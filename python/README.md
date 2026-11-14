# Consilium API <!-- pragma: allowlist secret -->

Research prototype. Not a medical device and not for clinical use.

Local development uses Python 3.12. The package also runs on Python 3.11.

```bash
cd python
uv sync
uv run uvicorn consilium.api.app:app --reload <!-- pragma: allowlist secret -->
```

`GET /api/health` returns `{"status":"ok"}`.

Export the OpenAPI document and regenerate the web client (no database):

```bash
cd typescript && bun run gen:api
```

Postgres for local development is `docker compose up -d` from the repo root
(`pgvector/pgvector:pg17`, database `consilium`). Then: <!-- pragma: allowlist secret -->

```bash
DATABASE_URL=postgresql://consilium:consilium@localhost:5432/consilium uv run consilium db migrate <!-- pragma: allowlist secret -->
```

`db migrate --schema-only` applies tables and leaves HNSW and GIN for
`db migrate --indexes-only` after a bulk load. `db status` lists applied files.

Load the invented fixture roster, cases, reports and two synthetic pyramidal slides.
Files are written under `STORAGE_ROOT` (default `data/`) and are not committed.
Running `seed` again replaces those rows and leaves the same counts.

```bash
uv run consilium db seed <!-- pragma: allowlist secret -->
uv run python -m consilium.db seed <!-- pragma: allowlist secret -->
```

`uv sync` installs OpenSlide (`openslide-python` and the `openslide-bin` wheel) with the API. Tile routes and the seed tests open slides with that wheel on Python 3.11 and 3.12; no apt package is required. `STORAGE_BACKEND=uc_volume` reads Unity Catalog Volume files through the Databricks SDK (`databricks-sdk`).

Copy the repo-root `.env.example` to `.env` to override local defaults. Do not put real secrets in git.

```bash
uv sync --group pipeline   # torch, transformers, and h5py: offline pipeline and CPU text encoders
```

`consilium.embed` encodes image-query text with the CONCH-Z text tower and report text with `BAAI/bge-small-en-v1.5`, both on CPU. Those weights stay out of git. The default test run uses an in-process mock and does not download them. Set `CONSILIUM_RUN_HF_INTEGRATION=1` to run the live checks; CONCH-Z also needs `HF_TOKEN`. <!-- pragma: allowlist secret -->

`uv run consilium --help` lists the `serve` command. <!-- pragma: allowlist secret -->

```bash
uv run python -m consilium.pipeline manifest --tier smoke --max-slide-gb 1.0 --seed 0 <!-- pragma: allowlist secret -->
uv run python -m consilium.pipeline download --workers 4 <!-- pragma: allowlist secret -->
uv run python -m consilium.pipeline extract --gpu 0 <!-- pragma: allowlist secret -->
uv run python -m consilium.pipeline project <!-- pragma: allowlist secret -->
uv run python -m consilium.pipeline thumbs <!-- pragma: allowlist secret -->
uv run python -m consilium.pipeline export <!-- pragma: allowlist secret -->
```

`manifest` is stage 1. It writes `data/cohort/cohort.csv` and `data/source/gdc_cases.parquet`. `download` streams each slide from the GDC (`GET /data/{gdc_file_id}`) to `data/slides/{slide_id}.svs`, checks the manifest size and the GDC MD5, and writes `data/trident/download_report.json`. `extract` reads level-0 dimensions, magnification, and microns-per-pixel from each SVS header into `data/trident/slide_headers.parquet`, then runs TRIDENT tissue segmentation, 512 px patching at 20x with no overlap, and `conch_v15` features into `data/trident/`. `project` multiplies those features by CONCH-Z `visual.proj_contrast` and L2-normalises them. `thumbs` writes `data/thumbs/{slide_id}.pack`. `export` writes `data/export/slide.parquet`, `patch.parquet`, and `concept.parquet`. `verify-alignment` saves the top thumbnails for two prompts on one slide. Those paths are git-ignored. A second run skips slides whose outputs already check out. The commands print seconds per slide and a projected time for the 200-slide demo tier.

TRIDENT itself is installed from GitHub on the GPU machine (`uv pip install -e /path/to/TRIDENT`). The PyPI package named `trident` is unrelated. `conch_v15` weights need `HF_TOKEN`.

## Before the demo

Research prototype. Not for clinical use. From `python/`, with Postgres migrated and the fixture data seeded, check the laptop before presenting:

```bash
uv run consilium preflight --case breast-FX-B042C <!-- pragma: allowlist secret -->
```

That runs the static checks only: non-secret settings, migrations, row counts, the case and its slide files, and both text encoders. `ANTHROPIC_API_KEY`, `HF_TOKEN` and `DATABRICKS_TOKEN` are reported as `set` or `not set`. The database URL is printed without userinfo. A missing index migration is a warning. A zero row count, a missing schema migration, or a slide that does not open is a failure. The process exits non-zero only when a check fails.

With the API already running (`uv run consilium serve` in another shell), warm the server process as well. The server loads its encoders lazily, so this is the warm-up the demo path actually needs: <!-- pragma: allowlist secret -->

```bash
uv run consilium preflight --api http://127.0.0.1:8000 --case breast-FX-B042C <!-- pragma: allowlist secret -->
```

The live checks call `GET /api/health`, the case, each slide's Deep Zoom descriptor, thumbnail and the `0_0` tile at the lowest pyramid levels, then one `POST /api/slides/{id}/heatmap` with `{"text": "glandular"}` and one `POST /api/search/reports` with `{"text": "adenocarcinoma"}`. Slide ids come from the case response. If that route is still the placeholder store (the seeded case is HTTP 404 and the placeholder case answers), the case check is a warning and the warm-up uses the database slide ids. If report search is still a stub (HTTP 501 or a stub payload), that check is a warning.

`--warm` fetches each slide and thumbnail pack into the local cache when `STORAGE_BACKEND=uc_volume`. `--ping-llm` makes one 5-token call through the configured provider. Without that flag the command does not call a model. The command does not write to Postgres or to the slide store, apart from filling that cache.
