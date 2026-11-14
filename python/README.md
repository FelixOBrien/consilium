# Consilium API <!-- pragma: allowlist secret -->

Research prototype. Not a medical device and not for clinical use.

Local development uses Python 3.12. The package also runs on Python 3.11.

```bash
cd python
uv sync
uv run uvicorn consilium.api.app:app --reload <!-- pragma: allowlist secret -->
```

`GET /api/health` returns `{"status":"ok"}`.

Postgres for local development is `docker compose up -d` from the repo root
(`pgvector/pgvector:pg17`, database `consilium`). Then: <!-- pragma: allowlist secret -->

```bash
DATABASE_URL=postgresql://consilium:consilium@localhost:5432/consilium uv run consilium db migrate <!-- pragma: allowlist secret -->
```

`db migrate --schema-only` applies tables and leaves HNSW and GIN for
`db migrate --indexes-only` after a bulk load. `db status` lists applied files.

Copy the repo-root `.env.example` to `.env` to override local defaults. Do not put real secrets in git.

```bash
uv sync --group pipeline   # torch and transformers: offline pipeline and CPU text encoders
uv sync --group tiles      # OpenSlide, for the tile server
```

`consilium.embed` encodes image-query text with the CONCH-Z text tower and report text with `BAAI/bge-small-en-v1.5`, both on CPU. Those weights stay out of git. The default test run uses an in-process mock and does not download them. Set `CONSILIUM_RUN_HF_INTEGRATION=1` to run the live checks; CONCH-Z also needs `HF_TOKEN`. <!-- pragma: allowlist secret -->

`uv run consilium --help` lists the `serve` command. <!-- pragma: allowlist secret -->

```bash
uv run python -m consilium.pipeline manifest --tier smoke --max-slide-gb 1.0 --seed 0 <!-- pragma: allowlist secret -->
```

That command is stage 1 of ingestion (the cohort manifest). It writes `data/cohort/cohort.csv` and `data/source/gdc_cases.parquet`, both git-ignored. Later ingestion stages are not part of this install yet. <!-- pragma: allowlist secret -->
