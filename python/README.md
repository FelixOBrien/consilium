# Consilium API <!-- pragma: allowlist secret -->

Research prototype. Not a medical device and not for clinical use.

Local development uses Python 3.12. The package also runs on Python 3.11.

```bash
cd python
uv sync
uv run uvicorn consilium.api.app:app --reload <!-- pragma: allowlist secret -->
```

`GET /api/health` returns `{"status":"ok"}`.

Copy the repo-root `.env.example` to `.env` to override local defaults. Do not put real secrets in git.

```bash
uv sync --group pipeline   # GPU stack: torch, timm, transformers
uv sync --group tiles      # OpenSlide, for the tile server
```

`uv run consilium --help` lists the `serve` command. Ingestion stages are not part of this install. <!-- pragma: allowlist secret -->
