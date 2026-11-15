# Consilium

A histopathology case workspace that treats diagnostic support as an information-retrieval problem. A pathologist opens a case, views the whole slide image and report, then finds precedent: similar tissue by morphology, similar cases by report text, and an agent that reads the retrieved reports and says who has reported the most cases like this one.

Built at Imperial AI Hack, 13–15 November 2026, for the Autonomous Agents track.

> Research prototype. Not a medical device and not for clinical use.

## How it works

1. **Ingest** — TCGA diagnostic slides from the NCI Genomic Data Commons are tiled with TRIDENT and each tissue patch is embedded with CONCH v1.5, then projected into the CONCH-Z image-text space. Reports are chunked and embedded separately.
2. **Store** — patches, slides, reports and annotations live in Postgres with pgvector (Databricks Lakebase when deployed), with Delta tables in Unity Catalog as the lakehouse copy.
3. **Retrieve** — click a region of tissue to find similar tissue in other cases, type a description to find matching patches, or run hybrid keyword and semantic search over reports.
4. **Consult** — a Claude agent uses those searches as tools, reads the reports it finds, and returns a cited brief, including which pathologists reported the most relevant cases.

## Repository

| Path | Contents |
| --- | --- |
| [docs/](docs/index.md) | Vision, hackathon context, architecture, and feature / story / model / screen specs |
| `python/` | FastAPI API, search, agent, tile server and ingestion pipeline |
| `typescript/` | SvelteKit web app |

Python setup is in [python/README.md](python/README.md). Web setup is added as that scaffold lands.

## Models, datasets and APIs used

| Kind | Name | Used for | Licence |
| --- | --- | --- | --- |
| Dataset | [TCGA diagnostic slides](https://portal.gdc.cancer.gov/) via the GDC API | Whole slide images and clinical labels | GDC open access (NIH GDS policy) |
| Dataset | [TCGA-Reports](https://github.com/tatonetti-lab/tcga-path-reports) (Kefeli et al.) | Pathology report text | CC BY 4.0 |
| Model | [CONCH-Z](https://huggingface.co/MahmoodLab/CONCH-Z) with the CONCH v1.5 vision encoder | Patch and image-query text embeddings | CC-BY-NC-ND 4.0 |
| Model | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | Report chunk embeddings | MIT |
| Library | [TRIDENT](https://github.com/mahmoodlab/TRIDENT) | Tissue segmentation, patching, feature extraction | See repository |
| API | Anthropic Claude API | Consult agent | — |
| Library | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Streaming tool-use loop for the consult agent | MIT |
| Library | [FastAPI](https://fastapi.tiangolo.com/) | HTTP API | MIT |
| Library | [Uvicorn](https://www.uvicorn.org/) | ASGI server | BSD-3-Clause |
| Library | [Pydantic](https://docs.pydantic.dev/) | API models and settings | MIT |
| Library | [openapi-typescript](https://github.com/openapi-ts/openapi-typescript) | Generate the TypeScript API types | MIT |
| Library | [openapi-fetch](https://github.com/openapi-ts/openapi-fetch) | Typed fetch client for the web app | MIT |
| Library | [psycopg](https://www.psycopg.org/) | Postgres driver | LGPL-3.0 |
| Library | [pgvector-python](https://github.com/pgvector/pgvector-python) | Postgres vector type | MIT |
| Library | [PyTorch](https://pytorch.org/) | Pipeline embeddings, not the API install | BSD-3-Clause |
| Library | [timm](https://github.com/huggingface/pytorch-image-models) | Pipeline vision backbones | Apache-2.0 |
| Library | [Transformers](https://github.com/huggingface/transformers) | CONCH-Z and report encoders | Apache-2.0 |
| Library | [Hugging Face Hub](https://github.com/huggingface/huggingface_hub) | Model download for the pipeline | Apache-2.0 |
| Library | [OpenSlide](https://openslide.org/) (`openslide-python`, `openslide-bin`) | SVS header reads, fixture slides, and Deep Zoom tiles from the original slide file. The wheel bundles the library, so no system packages are required. | LGPL-2.1 |
| Library | [Databricks SDK for Python](https://github.com/databricks/databricks-sdk-py) | Fetch slides from a Unity Catalog Volume into the local cache | Apache-2.0 |
| Library | [MLflow Tracing](https://mlflow.org/docs/latest/genai/tracing/lightweight-sdk/) (`mlflow-tracing`) | Optional consult-turn traces. The lightweight SDK, not the full MLflow package. Off unless `MLFLOW_TRACING_ENABLED` is set. | Apache-2.0 |
| Library | [PyArrow](https://arrow.apache.org/) | Cohort manifest clinical table (`gdc_cases.parquet`) | Apache-2.0 |
| Library | [NumPy](https://numpy.org/) | Synthetic fixture images and unit vectors | BSD-3-Clause |
| Library | [h5py](https://www.h5py.org/) | Read and validate TRIDENT coordinate and feature files | BSD-3-Clause |
| Library | [Pillow](https://python-pillow.org/) | JPEG thumbnails in fixture packs | MIT-CMU |
| Library | [tifffile](https://github.com/cgohlke/tifffile) | Synthetic pyramidal TIFF fixture slides | BSD-3-Clause |
| Platform | Databricks Free Edition (Unity Catalog, Delta, Lakebase, Apps) | Lakehouse, vector search, app hosting | — |

Pathologist identities, sign-out dates, case assignments and multi-donor longitudinal patient links are synthetic: TCGA reports are de-identified and do not identify report authors or longitudinal clinical accessions.

## Databricks App

The laptop run is the demo path. The App is the deployed copy, and it is not public. Apps stop 24 hours after start or redeploy, so restart on Sunday morning before judging.

One command builds the static client, stages a git-ignored bundle (`build/databricks-app/`, never commit it), syncs that bundle, and deploys. It refuses to run until `CONSILIUM_DEPLOY_DATABRICKS=1` is set. Do that only after the lakehouse load (SKO-280) has put real cohort data in the Volume and Lakebase. <!-- pragma: allowlist secret -->

```bash
export DATABRICKS_HOST="https://<workspace-host>"   # no trailing slash  # pragma: allowlist secret
export DATABRICKS_TOKEN="<pat>"
export DATABRICKS_APP_SOURCE="/Workspace/Users/<you>/consilium-app"  # pragma: allowlist secret
export DATABRICKS_APP_NAME="consilium"              # optional  # pragma: allowlist secret
CONSILIUM_DEPLOY_DATABRICKS=1 scripts/deploy_databricks_app.sh  # pragma: allowlist secret
```

`scripts/stage_databricks_app.sh` is the build half on its own: `bun install --frozen-lockfile`, `bun run --filter web build`, then the Python package, `uv.lock`, `app.yaml`, and `static_web/`. The staged `pyproject.toml` installs the `pipeline` group so the CPU text encoders are present. There is no `requirements.txt`, so the App installs with `uv sync`.

Attach these resource keys on the App before the first deploy. `python/databricks/app.yaml` references them with `valueFrom` and does not contain secret values.

| Key | Kind | Becomes |
| --- | --- | --- |
| `volume` | Unity Catalog volume | `STORAGE_ROOT` and `DATABRICKS_VOLUME_ROOT` (`/Volumes/.../raw`) |
| `postgres` | Lakebase database | `LAKEBASE_ENDPOINT` (endpoint path, not a libpq URL) |
| `database-url` | secret | `DATABASE_URL`, with `sslmode=require` |
| `anthropic-api-key` | secret | `ANTHROPIC_API_KEY` |
| `hf-token` | secret | `HF_TOKEN` |

The process listens on `0.0.0.0` and `${DATABRICKS_APP_PORT:-8000}`. `LLM_PROVIDER=anthropic`. `STORAGE_BACKEND=uc_volume`. `SEARCH_BACKEND=pgvector`. `SLIDE_CACHE_DIR=/tmp/consilium-slides` and `SLIDE_CACHE_MAX_GB=4` cap cached slides on the App's ephemeral disk, beside the Hugging Face files in `/tmp/consilium-hf`. The default App size is 2 vCPU and 6 GB RAM. Text encoders load on the first encode, so `/api/health` stays light. A local run of `create_app` with `MockTextEncoder` peaked at 87 MiB RSS, and the static client is 663,677 bytes. The live CONCH-Z text tower and bge-small are outside that measurement; they load into the 6 GB App on first use. <!-- pragma: allowlist secret -->

Sunday morning, before judging:

```bash
databricks apps start consilium  # pragma: allowlist secret
```

`python/databricks/app.yaml` is the committed runtime config. The step-by-step morning check is the deploy runbook kept with the project notes.
