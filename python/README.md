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
uv sync --group pipeline   # GPU stack: torch, timm, transformers
uv sync --group tiles      # OpenSlide, for the tile server
```

`uv run consilium --help` lists the `serve` command. <!-- pragma: allowlist secret -->

```bash
uv run python -m consilium.pipeline manifest --tier smoke --max-slide-gb 1.0 --seed 0 <!-- pragma: allowlist secret -->
```

That command is stage 1 of ingestion (the cohort manifest). It writes `data/cohort/cohort.csv` and `data/source/gdc_cases.parquet`, both git-ignored. Later ingestion stages are not part of this install yet. <!-- pragma: allowlist secret -->
