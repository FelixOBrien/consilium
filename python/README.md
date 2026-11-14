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
uv sync --group pipeline   # torch and transformers: offline pipeline and CPU text encoders
uv sync --group tiles      # OpenSlide, for the tile server
```

`consilium.embed` encodes image-query text with the CONCH-Z text tower and report text with `BAAI/bge-small-en-v1.5`, both on CPU. Those weights stay out of git. The default test run uses an in-process mock and does not download them. Set `CONSILIUM_RUN_HF_INTEGRATION=1` to run the live checks; CONCH-Z also needs `HF_TOKEN`. <!-- pragma: allowlist secret -->

`uv run consilium --help` lists the `serve` command. Ingestion stages are not part of this install. <!-- pragma: allowlist secret -->
