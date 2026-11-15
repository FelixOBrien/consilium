# Consilium <!-- pragma: allowlist secret -->

Consilium is a histopathology case workspace for **information retrieval and precedent search, not AI diagnosis**. A pathologist opens a case, views the whole-slide image and the report, then finds precedent: similar tissue by morphology, similar cases by report text, and a colleague who has reported cases like this one. The product retrieves and summarises prior cases, always with citations. It does not state a diagnosis for the open case. <!-- pragma: allowlist secret -->

Built at [Imperial AI Hack](https://imperialaihack.com/), 13–15 November 2026, for Track 02, Autonomous Agents.

> **Research prototype. Not a diagnostic device and not for clinical use.**

> **Synthetic data.** The pathologist roster, case assignments, sign-out dates, and synthetic longitudinal links between cases are not real clinical records. Pathologist rows are marked `is_synthetic`. Patient rows whose history joins more than one TCGA donor are marked `is_synthetic_linkage`. The diagnostic slides and the pathology report texts under those rows are public and de-identified: TCGA whole-slide images from the NCI Genomic Data Commons, and the TCGA-Reports corpus.

## How it works

1. **Ingest** — TCGA diagnostic slides from the NCI Genomic Data Commons are tiled with TRIDENT (tissue segmentation `hest`, 512 px patches at 20×, no overlap). Each patch is embedded with CONCH v1.5 (`conch_v15`) and projected into the CONCH-Z image-text space (768-d). Reports are chunked and embedded separately with `BAAI/bge-small-en-v1.5` (384-d). The two spaces are never compared.
2. **Store** — patches, slides, reports, and the synthetic roster live in Postgres with pgvector. Locally that is Docker. On Databricks it is Lakebase, with Delta tables in Unity Catalog as the lakehouse copy.
3. **Retrieve** — open a case and pan the slide, click a region to find similar tissue in other cases, or type a phrase and see which patches on the slide sit nearest that phrase. Report search fuses keyword rank (`tsvector`) and semantic rank (pgvector).
4. **Consult** — a Claude agent calls those searches as tools, reads the reports it finds, and returns a cited brief. Any count of how many cases a pathologist reported comes from SQL (`rank_pathologists`), not from the model. Open cases withhold their report text and diagnosis labels.

## Repository

| Path | Contents |
| --- | --- |
| [docs/](docs/index.md) | Vision, hackathon context, architecture, and feature / story / model / screen specs |
| `python/` | FastAPI API, search, agent, tile server, and ingestion pipeline. Stage-by-stage notes are in [python/README.md](python/README.md). |
| `python/databricks/` | Lakehouse notebook and Databricks App config, as those changes land |
| `typescript/` | Bun and Turborepo. The case workspace is `apps/web` (SvelteKit). | <!-- pragma: allowlist secret -->
| `data/` | Local slides, features, and parquet. Git-ignored. Never commit. |

Screens were designed in Figma and built with shadcn-svelte. Figma is a design tool, not a runtime dependency.

## Run it from a clean clone

You need Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), and [Bun](https://bun.sh/) 1.3. The API also runs on Python 3.11. Weights, slides, and `.env` stay out of git.

### Postgres

From the repository root:

```bash
docker compose up -d
cp .env.example .env
```

Compose starts Postgres 17 with pgvector (`pgvector/pgvector:pg17`), including `halfvec`. The local role, password, and database name are all `consilium`. That password is only for this Docker database. <!-- pragma: allowlist secret -->

Put this in `.env`. Settings read the file from the repository root:

```bash
DATABASE_URL=postgresql://consilium:consilium@localhost:5432/consilium # pragma: allowlist secret
```

If `DATABASE_URL` is empty, the API falls back to `postgresql://localhost:5432/consilium` (the current operating-system user, and no password). That is not the Docker role, so set the URL above before migrating. <!-- pragma: allowlist secret -->

### API

```bash
cd python
uv sync
uv run consilium db migrate # pragma: allowlist secret
uv run consilium db seed # pragma: allowlist secret
uv run consilium serve # pragma: allowlist secret
```

`serve` listens on `http://127.0.0.1:8000`. `GET /api/health` returns `{"status":"ok"}`.

`db migrate` applies the schema and the HNSW and GIN indexes. `db seed` loads an invented roster, cases, reports, and two synthetic pyramidal slides under `data/` (not committed). Running `seed` again replaces those rows.

`ANTHROPIC_API_KEY` is required only when you send a consult message. The default model is `claude-sonnet-4-5` (`ANTHROPIC_MODEL` overrides it). `HF_TOKEN` is required only to download gated CONCH-Z and CONCH v1.5 weights. TCGA slides and TCGA-Reports need no token.

The default install does not include the text encoders. Add them before phrase search, report search, or ingestion:

```bash
uv sync --group pipeline
```

That group installs PyTorch, torchvision, timm, Transformers, Hugging Face Hub, and h5py. Image-query text uses the CONCH-Z text tower. Report text uses `transformers.AutoModel` on `BAAI/bge-small-en-v1.5` (MIT weights, 384-d, CLS pooling, L2-normalised). The `sentence-transformers` package is not a dependency. `scikit-image` is not a dependency, including on the open branches checked for this list.

### Web

From `typescript/`, in a second shell, with the API already running:

```bash
bun install
bun run dev
```

`bun run dev` is the Turborepo `dev` task. The case workspace is the `web` app. It proxies `/api` to `http://127.0.0.1:8000` and serves the UI at `http://127.0.0.1:5173`. The same command also starts the leftover `docs` app on port 3001. To start only the workspace: <!-- pragma: allowlist secret -->

```bash
bun run dev --filter web
```

### Demo cohort on a GPU

TRIDENT is not on PyPI. The PyPI project named `trident` is an unrelated package. On the GPU machine, clone [TRIDENT](https://github.com/mahmoodlab/TRIDENT) and install that checkout (`uv pip install -e /path/to/TRIDENT`). Set `HF_TOKEN`. Then, from `python/`:

```bash
uv sync --group pipeline
uv run consilium pipeline run --tier demo --gpu 0 --replace-fixtures # pragma: allowlist secret
```

`run` builds the cohort manifest from the GDC API and TCGA-Reports, downloads `.svs` files, extracts `conch_v15` features, projects them into CONCH-Z, writes thumbnail packs and parquet under `data/`, and loads Postgres. `--replace-fixtures` removes the seeded fixture cases first. Other cases stay. `--tier smoke` is the 10-slide check. `--gpu -1` asks TRIDENT for CPU.

To load an export that already exists, still from `python/`:

```bash
uv run consilium pipeline load --from ../data/export --replace-fixtures # pragma: allowlist secret
```

`--from` is relative to the shell's current directory. `../data/export` is the git-ignored export at the repository root when the shell is in `python/`.

### Retrieval evaluation, preflight, and Databricks

The commands in this section are implemented on open branches. `consilium --help` on this commit does not list `evaluate`, `preflight`, `subset`, `upload-volume`, or `reconcile` until those branches are merged. The invocations match the branch that adds each command. <!-- pragma: allowlist secret -->

Held-out retrieval scores (ICD-O-3 morphology group and ICD-10 category), written to `data/eval/report.md` and `data/eval/report.json`. This is a retrieval check, not a diagnosis:

```bash
uv run consilium pipeline evaluate # pragma: allowlist secret
```

`evaluate --encoder mock` skips the Hugging Face download.

Laptop check before a live demo, after migrate and seed. The second command warms an API that is already running (`serve` in another shell): health, the case, Deep Zoom tiles, one heatmap for the phrase `glandular`, and one report search. It does not call Claude unless you pass `--ping-llm`.

```bash
uv run consilium preflight --case breast-FX-B042C # pragma: allowlist secret
uv run consilium preflight --api http://127.0.0.1:8000 --case breast-FX-B042C # pragma: allowlist secret
```

Lakehouse path. Lakebase Free Edition stores at most 512 MB, so the served load is a subset, not every demo patch. `SEARCH_BACKEND` stays `pgvector`. There is no `lakebase_ann` or `lakebase_bm25` index.

```bash
uv run consilium pipeline subset --from ../data/export --out ../data/export_lakebase --max-cases 45 # pragma: allowlist secret
uv run consilium pipeline upload-volume --from ../data/export_lakebase # pragma: allowlist secret
uv run consilium pipeline load --from ../data/export_lakebase --replace-fixtures --max-cases 45 # pragma: allowlist secret
```

`upload-volume` reads `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `DATABRICKS_VOLUME_ROOT` (a `/Volumes/<catalog>/<schema>/raw` path). The notebook `python/databricks/medallion_lakebase.py` builds Bronze, Silver, and Gold Delta tables on serverless Spark and loads Lakebase. Widgets: `catalog` (default `main`) and `schema` (default `consilium`). <!-- pragma: allowlist secret -->

Databricks App. The laptop remains the demo path. The App is not public, and it stops 24 hours after a start or a redeploy. From the repository root, after the lakehouse load:

```bash
export DATABRICKS_HOST="https://<workspace-host>" # pragma: allowlist secret
export DATABRICKS_TOKEN="<pat>"
export DATABRICKS_APP_SOURCE="/Workspace/Users/<you>/consilium-app" # pragma: allowlist secret
export DATABRICKS_APP_NAME="consilium" # pragma: allowlist secret
CONSILIUM_DEPLOY_DATABRICKS=1 scripts/deploy_databricks_app.sh # pragma: allowlist secret
```

`DATABRICKS_HOST` must not have a trailing slash. Attach the App resources `volume`, `postgres`, `database-url`, `anthropic-api-key`, and `hf-token` before the first deploy. `python/databricks/app.yaml` names them and does not hold secret values. On Sunday morning, before judging:

```bash
databricks apps start consilium # pragma: allowlist secret
```

Consult traces stay off unless `MLFLOW_TRACING_ENABLED` is set, together with `DATABRICKS_HOST` and `DATABRICKS_TOKEN`, or a local `MLFLOW_TRACKING_URI`. The default experiment name is `/Shared/consilium-consult`. The package is `mlflow-tracing`, not the full `mlflow` distribution. <!-- pragma: allowlist secret -->

## Models, datasets and APIs used

Weights, slides, embeddings, and parquet are not in this repository. CONCH-Z and CONCH v1.5 are CC-BY-NC-ND 4.0 (Mahmood Lab), gated on Hugging Face, and are not redistributed. The report encoder slug in code is `BAAI/bge-small-en-v1.5`, loaded with Transformers rather than `sentence-transformers`. The patch encoder flag passed to TRIDENT is `conch_v15`. TITAN is not called.

The table is the hackathon declaration list for the API, the web app, and the Databricks path, including optional consult tracing.

| Kind | Name | Used for | Licence |
| --- | --- | --- | --- |
| Dataset | [TCGA diagnostic slides](https://portal.gdc.cancer.gov/) (NCI GDC open-access FFPE H&E, Aperio `.svs`) | Whole-slide images and clinical fields (`primary_diagnosis`, ICD-O-3 morphology, ICD-10) | GDC Open Access Data Use Policy; NIH Genomic Data Sharing policy |
| Dataset | [TCGA-Reports](https://github.com/tatonetti-lab/tcga-path-reports) (Kefeli and Tatonetti, *Patterns*, 2024; also [Mendeley Data](https://data.mendeley.com/datasets/hyg5xkznpx/1)) | OCR pathology report text, joined on the 12-character TCGA barcode | CC BY 4.0 |
| Model | [CONCH-Z](https://huggingface.co/MahmoodLab/CONCH-Z) | Zero-shot text tower and `visual.proj_contrast` projection into the shared 768-d image-text space | CC-BY-NC-ND 4.0 |
| Model | CONCH v1.5 (`conch_v15`) through [TRIDENT](https://github.com/mahmoodlab/TRIDENT) | Patch features before projection: 512 px at 20×, no overlap | CC-BY-NC-ND 4.0 |
| Model | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | Report chunk embeddings | MIT |
| Library | [TRIDENT](https://github.com/mahmoodlab/TRIDENT) | Tissue segmentation, patching, feature extraction | See repository |
| API | Anthropic Claude API | Consult agent | — |
| Library | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Streaming tool-use loop for the consult agent | MIT |
| Library | [FastAPI](https://fastapi.tiangolo.com/) | HTTP API | MIT |
| Library | [Uvicorn](https://www.uvicorn.org/) | ASGI server | BSD-3-Clause |
| Library | [Pydantic](https://docs.pydantic.dev/) | API models and settings | MIT |
| Library | [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Streaming tool-use loop for the consult agent. Locked releases from 2.0.0 are Apache-2.0; earlier releases were MIT. | Apache-2.0 |
| Library | [MLflow Tracing](https://mlflow.org/docs/latest/genai/tracing/) (`mlflow-tracing`) | Optional consult-turn traces. Off unless `MLFLOW_TRACING_ENABLED` is set. Not the full MLflow package. | Apache-2.0 |
| Library | [Svelte](https://svelte.dev/) 5 and [SvelteKit](https://svelte.dev/docs/kit) | Static case workspace (`typescript/apps/web`) | MIT | <!-- pragma: allowlist secret -->
| Library | [Tailwind CSS](https://tailwindcss.com/) | Styling | MIT |
| Library | [shadcn-svelte](https://www.shadcn-svelte.com/) | UI components mapped from the Figma screens | MIT |
| Library | [Bits UI](https://bits-ui.com/) | Headless primitives used by shadcn-svelte | MIT |
| Library | [OpenSeadragon](https://openseadragon.github.io/) | Deep Zoom whole-slide viewer | BSD-3-Clause |
| Library | [Lucide](https://lucide.dev/) (`@lucide/svelte`) | Icons | ISC |
| Platform | [Figma](https://www.figma.com/) | Screen design and design tokens | Figma (Education plan for this hackathon) |
| API | [NCI GDC REST API](https://docs.gdc.cancer.gov/API/Users_Guide/Getting_Started/) | Open-access slide download and clinical fields. No token. | GDC Open Access |
| API | [Hugging Face Hub](https://huggingface.co/) | Gated CONCH-Z and CONCH v1.5 weights, and the public bge-small weights | Model licences in the rows above; Hub client is Apache-2.0 |
| API | [Anthropic Messages API](https://platform.claude.com/docs/en/api/messages) | Consult agent. Default model `claude-sonnet-4-5` (`ANTHROPIC_MODEL`) | Anthropic API |
| Library | [openapi-typescript](https://github.com/openapi-ts/openapi-typescript) | Generate the TypeScript API types | MIT |
| Library | [openapi-fetch](https://github.com/openapi-ts/openapi-fetch) | Typed fetch client for the web app | MIT |
| Library | [psycopg](https://www.psycopg.org/) | Postgres driver | LGPL-3.0 |
| Library | [pgvector](https://github.com/pgvector/pgvector) (Postgres extension and Python package) | `halfvec(768)` and `vector(384)`, plus the Python adapter | PostgreSQL License (extension); MIT (Python package) |
| Library | [PyTorch](https://pytorch.org/) (and torchvision) | Pipeline embeddings, not the default API install | BSD-3-Clause |
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
| Library | [OpenSeadragon](https://openseadragon.github.io/) | Deep zoom slide viewer | BSD-3-Clause |
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
