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

Setup and run instructions are added as the scaffolds land.

## Models, datasets and APIs used

| Kind | Name | Used for | Licence |
| --- | --- | --- | --- |
| Dataset | [TCGA diagnostic slides](https://portal.gdc.cancer.gov/) via the GDC API | Whole slide images and clinical labels | GDC open access (NIH GDS policy) |
| Dataset | [TCGA-Reports](https://github.com/tatonetti-lab/tcga-path-reports) (Kefeli et al.) | Pathology report text | CC BY 4.0 |
| Model | [CONCH-Z](https://huggingface.co/MahmoodLab/CONCH-Z) with the CONCH v1.5 vision encoder | Patch and image-query text embeddings | CC-BY-NC-ND 4.0 |
| Model | [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | Report chunk embeddings | MIT |
| Library | [TRIDENT](https://github.com/mahmoodlab/TRIDENT) | Tissue segmentation, patching, feature extraction | See repository |
| API | Anthropic Claude API | Consult agent | — |
| Platform | Databricks Free Edition (Unity Catalog, Delta, Lakebase, Apps) | Lakehouse, vector search, app hosting | — |

Pathologist identities, sign-out dates, case assignments and multi-donor longitudinal patient links are synthetic: TCGA reports are de-identified and do not identify report authors or longitudinal clinical accessions.
