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

`uv sync --group tiles` installs OpenSlide. The seed tests open the generated slides with it.

Copy the repo-root `.env.example` to `.env` to override local defaults. Do not put real secrets in git.

```bash
uv sync --group pipeline   # torch, transformers, and h5py: offline pipeline and CPU text encoders
uv sync --group tiles      # OpenSlide, for SVS headers and the tile server
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
