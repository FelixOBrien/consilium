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
| Library | [Databricks SDK for Python](https://github.com/databricks/databricks-sdk-py) | Fetch slides from a Unity Catalog Volume, and upload parquet, thumbnail packs, and slides | Apache-2.0 |
| Library | [PyArrow](https://arrow.apache.org/) | Cohort manifest clinical table (`gdc_cases.parquet`) | Apache-2.0 |
| Library | [NumPy](https://numpy.org/) | Synthetic fixture images and unit vectors | BSD-3-Clause |
| Library | [h5py](https://www.h5py.org/) | Read and validate TRIDENT coordinate and feature files | BSD-3-Clause |
| Library | [Pillow](https://python-pillow.org/) | JPEG thumbnails in fixture packs | MIT-CMU |
| Library | [tifffile](https://github.com/cgohlke/tifffile) | Synthetic pyramidal TIFF fixture slides | BSD-3-Clause |
| Platform | Databricks Free Edition (Unity Catalog, Delta, Lakebase, Apps) | Lakehouse, vector search, app hosting | — |

Pathologist identities, sign-out dates, case assignments and multi-donor longitudinal patient links are synthetic: TCGA reports are de-identified and do not identify report authors or longitudinal clinical accessions.
