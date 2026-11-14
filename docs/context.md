# Context

Constraints the project works within: the hackathon, the track, the dataset, the model licences and the platform. Facts here were read from the sources linked on Sat 14 Nov 2026 (the dataset section after the switch to TCGA that evening); items marked *unverified* have not been confirmed first-hand.

## Hackathon

[Imperial AI Hack](https://imperialaihack.com/), Fri 13 – Sun 15 Nov 2026, Huxley Building, Imperial College London. All times UK.

| When | What |
| --- | --- |
| Sat 12:10 | Building starts |
| Sat 21:00 | Building closes. No overnight hacking on site; work continues remotely. |
| Sun 10:00 | Doors reopen |
| **Sun 12:00** | **Submissions close. Nothing can be changed after this.** |
| Sun 13:00–16:30 | Judging: live presentation to the judges. Autonomous Agents is judged in Blackett LT1. |
| Sun 17:00 | Track winners present on the main stage; prizes at 17:30 |

### Rules

- All project code must be written during the hackathon. Planning and research beforehand are allowed.
- Pretrained models, public APIs and open-source libraries are allowed, and must be declared.
- Teams of 1 to 4. This team is one person working with AI agents.

### Submission, on Devpost before the freeze

- Public GitHub repository with a README
- Short description: problem, what was built, how it works
- List of APIs, models and datasets used (kept current in the root [README.md](../README.md))

No demo video. The project is presented live, so the demo must run reliably from a laptop.

### Credits available to every participant

Anthropic $50, Databricks Free Edition, MongoDB $50 Atlas, Figma Education, Adaption 1,250 credits, fal $25, ElevenLabs Creator, Lovable Pro, Tamarind Bio 200 jobs. Claimed under *My Pass* on the hackathon site.

The $50 of Anthropic credit is the budget for the consult agent, including development. Default to a mid-tier model and keep tool results short.

## Track and prizes

A team enters one main track and may also go for the extra prizes.

**Entered: Track 02, Autonomous Agents** — "Agents that research, write and run code, and reliably finish real multi-step tasks." Sponsors: Databricks, Linkup, Synthesia, Tavily, MongoDB. 1st £500, 2nd £200.

| Target | Prize | What it rewards | How we qualify |
| --- | --- | --- | --- |
| Track 02 placing | £500 / £200 | A reliable multi-step agent | The consult agent: searches by morphology and by text, reads reports, aggregates authorship, returns a cited brief. |
| Databricks bounty | £960 + swag | "Build on the Databricks Data Intelligence Platform: a pipeline, agent or app. Scored on creativity, technical depth and real-world impact." | Pipeline (Volume → Delta → Lakebase), agent, and app all on Databricks. |
| Figma Best-Designed AI Product | £960 + merch | "An AI product as well designed as it is smart, designed in Figma or built with Figma Make." Evidence of Figma use must be shown in the presentation. | Screens designed in Figma before they are built. |

Not pursued: the MongoDB bounty (Atlas at the core), because the store is Lakebase and running both splits the effort. Track 01, AI for Science, was considered and not entered: its sponsors and bounty centre on molecular models.

## Dataset: TCGA

The Cancer Genome Atlas (TCGA) diagnostic slides from the NCI [Genomic Data Commons](https://portal.gdc.cancer.gov/) (GDC), paired with the [TCGA-Reports](https://github.com/tatonetti-lab/tcga-path-reports) machine-readable pathology reports. It is used because both halves download with no login or approval and one patient pairs a diagnostic slide with a report.

HistAI was the first choice. It was dropped on Sat 14 Nov 2026 because every HistAI slide repository on Hugging Face requires manual approval by HistAI, which could not be relied on before the freeze.

### Slides: GDC

| Property | Value |
| --- | --- |
| Hosting | GDC API, `https://api.gdc.cancer.gov`. Open access tier: no token. Download one file with `GET /data/{file_id}`. |
| Selection | `files` endpoint filtered on `cases.project.program.name = TCGA`, `data_type = Slide Image`, `experimental_strategy = Diagnostic Slide`, `access = open`. 11,901 files. |
| Format | Aperio `.svs`, one per file. File name is `{slide barcode}.{uuid}.svs`, for example `TCGA-38-4631-01Z-00-DX1.….svs`. `DX1` is the first diagnostic slide. |
| Magnification | Mostly 40x (0.25 µm/px), some 20x; read from the SVS header (`aperio.AppMag`, `aperio.MPP`). *Not counted.* |
| Stain | H&E. Diagnostic slides are formalin-fixed, paraffin-embedded. |
| Size | Median 0.4–1.1 GB per file, depending on the project. |
| Clinical data | GDC `cases` endpoint: `project.project_id`, `demographic.sex_at_birth`, `demographic.age_at_index`, and per diagnosis `primary_diagnosis`, `morphology` (ICD-O-3), `icd_10_code`. |
| Licence | Open access data under the NIH Genomic Data Sharing policy; no restriction on use. Cite TCGA and the GDC as their publication guidelines ask. |

Open diagnostic slides in the projects mapped to a specialty:

| Specialty | TCGA projects | Slides | Slides under 1 GB |
| --- | --- | --- | --- |
| `breast` | BRCA | 1,133 | 587 |
| `thorax` | LUAD, LUSC | 1,053 | 737 |
| `colorectal` | COAD, READ | 625 | 525 |
| `gastrointestinal` | STAD, ESCA | 600 | 365 |
| `skin` | SKCM | 475 | 198 |
| `hematologic` | DLBC | 44 | 31 |

### Reports: TCGA-Reports

| Property | Value |
| --- | --- |
| Hosting | `TCGA_Reports.csv.zip` in the [tatonetti-lab/tcga-path-reports](https://github.com/tatonetti-lab/tcga-path-reports) repository (10.9 MB), also on [Mendeley Data](https://data.mendeley.com/datasets/hyg5xkznpx/1). |
| Licence | CC BY 4.0. Cite Kefeli et al., *TCGA-Reports* ([paper](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10935496/)). |
| Rows | 9,523, one per patient. |
| Columns | `patient_filename` (`{patient barcode}.{uuid}`, for example `TCGA-BP-5195.25c0b433-…`) and `text`. |
| Join | The first 12 characters of `patient_filename` are the patient barcode, which equals the GDC case `submitter_id` and the first 12 characters of the slide file name. |
| Text | The original report PDF, OCR'd with AWS Textract and cleaned: one block of text per report, median about 2,900 characters. |

### Known quality problems

Checked against the CSV on Sat 14 Nov 2026 unless marked *unverified*:

- **No fields.** A report is one string. Headings are inconsistent across the contributing hospitals: about 63% of reports have a diagnosis heading, 50% a clinical history heading, 37% a gross description heading and 16% a microscopic heading. Sections are extracted best-effort ([report](models/report.md#source)); the full text is always kept.
- **OCR noise.** Misread words (for example `Recelpt` for `Receipt`), broken line joins and leftover form text.
- **Every case is cancer.** TCGA collected primary tumours, so there are no benign or inflammatory cases. Precedent is between tumour subtypes, grades and patterns.
- **Diagnoses in GDC can repeat.** A case may carry several `diagnoses` entries, most `Not Reported`. Use the entry with a non-empty `primary_diagnosis` and `classification_of_tumor = primary`.
- **Slides are large.** Download time and disk set the cohort size. Prefer each case's smallest diagnostic slide.
- **Hematologic is thin.** DLBC has 44 open diagnostic slides; that specialty takes what exists.
- Some reports cover several specimens or include a synoptic checklist. *Unverified* how many.

### What the dataset does not have

**No report author.** TCGA reports are de-identified and do not identify the pathologist. The "who to consult" feature needs authorship, so pathologists are synthetic: a small seeded roster assigned to reports by specialty. This is disclosed in the README and in the app.

**No sign-out or accession dates, and mostly one specimen per donor.** Dates are synthetic. Where a TCGA donor has multiple distinct specimens in GDC they share one `patient`; to exercise longitudinal patient history ([F-12](features/F12-patient-history.md)) across the demo cohort, stage 7 also deterministically links ~15–20% of compatible cases into multi-case longitudinal patients (`patient.is_synthetic_linkage = true`), disclosed in the README and in the app.

### Cohort

The app runs on a sample, sized to what one GPU and one evening can download and process.

| Tier | Slides | Purpose |
| --- | --- | --- |
| `smoke` | 10 | Proves the pipeline end to end before the full run. |
| `demo` | about 200, one diagnostic H&E slide per case, balanced across breast, thorax, colorectal, gastrointestinal, hematologic and skin | The submission. Under 200 GB of slides with the 1 GB per-slide cap. |
| `stretch` | 500 or more | Only if the demo tier is loaded and searchable with time to spare. |

About 10 demo cases are held out as open, unreported cases: their real reports are stored but hidden, so the worklist has cases to work on and retrieval quality can be measured.

## Model licences

| Model | Licence | Consequence |
| --- | --- | --- |
| CONCH-Z and CONCH v1.5 (MahmoodLab) | CC-BY-NC-ND 4.0, gated to institutional Hugging Face accounts | Non-commercial research only. Access is already approved for this team. Weights and derived features are never committed or redistributed. |
| BAAI/bge-small-en-v1.5 | MIT | No restriction. |

Virchow2 was the alternative considered. See [architecture.md](architecture.md#decisions) for why it was not chosen.

## Platform: Databricks Free Edition

Checked against the live Free Edition account and its Lakebase project on Sat 14 Nov 2026. The published limits are from the [limitations page](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations) (page updated 18 Oct 2026). Numbers that page does not give were read from the account the same day.

| Limit | Effect on the design |
| --- | --- |
| Serverless compute only. No GPU serving, no custom models on GPU, no provisioned throughput. | Embeddings are computed off-platform on a rented GPU. Query-time text encoding runs on CPU in the app. |
| Outbound internet is limited to an unpublished trusted-domain list. | Serverless compute can reach `https://api.anthropic.com` and `https://huggingface.co`. Details below. The App itself is still started in the deploy issue, and the laptop remains a fallback. |
| One Lakebase project (Postgres 17) in AWS `us-east-2`. This project's read-write endpoint is fixed at 1 CU and suspends after 24 hours idle. | One Postgres database for everything served. The index build cannot ask this endpoint for a larger CU. |
| Durable Lakebase cap is 512 MB. Logical size on 14 Nov 2026 was 31 MB. | The full demo-tier patch table does not fit. Load a subset. Details below. |
| Up to 3 Apps. Each stops 24 hours after start or redeploy. The Apps API listed none. | Restart the App on Sunday morning before judging. |
| No custom storage locations. One metastore. Fair-use compute, and no published gigabyte quota for Volumes. | Slides and packs go in managed volume `raw`. Heavy compute stays off Databricks. |
| One AI Search endpoint, one search unit, and no Direct Vector Access. None is created in this account. | Search stays in pgvector. |
| Non-commercial use only. | Matches the model licences. |

Lakebase Search is off. `lakebase_ann` and `lakebase_bm25` are not installable here. `lakebase_vector`, `lakebase_text` and `lakebase_tokenizer` are allow-listed and were left uninstalled. Enabling Search cannot be undone and restarts compute, so the baseline stays plain pgvector and `tsvector`.

### External Postgres

`psql` 16 and `psycopg` 3 both connect from outside the account. The URL uses `sslmode=require` on port 5432; the session negotiated TLS 1.3 (`TLS_AES_256_GCM_SHA384`). The database name is `databricks_postgres`. Server version is PostgreSQL 17.12 on aarch64. A connection took 66 ms and `SELECT 1` took 2–3 ms.

Login is a native Postgres role: the project's `enable_pg_native_login` is on, and the configured password is not an OAuth token, so this URL does not expire hourly. The endpoint is `primary` on branch `production`, type read-write, state ACTIVE when probed. `max_connections` is 225. `shared_buffers` is 128 MB. A local file cache of about 1.5 GB sits beside that and is not extra durable storage.

The `vector` extension 0.8.7 is installed in `public` and stays installed. `public` has no tables.

### pgvector and full text

Inside a temporary schema, these all succeeded, and `EXPLAIN ANALYZE` used the indexes:

- HNSW on `halfvec(768)` with `halfvec_cosine_ops` (`<=>`) and `halfvec_ip_ops` (`<#>`)
- HNSW on `vector(384)` with `vector_cosine_ops` (`<=>`)
- GIN on a stored `tsvector` column (`@@`)

The schema was then dropped. Native pgvector answers both ANN and keyword search. Lakebase Search was not turned on.

### Volume and storage

Managed volume `raw` already exists at `/Volumes/<catalog>/<schema>/raw`. A 13-byte probe file uploaded through the Files API in about 300 ms, downloaded back unchanged, and was deleted. The volume root was empty afterwards. Neither the Files API nor the limitations page returns a volume capacity. Slide files for the demo tier (up to about 200 GB with the 1 GB per-slide cap) land in this volume under the fair-use policy.

Lakebase is the measured cap. `neon.max_cluster_size` is 512 MB and the branch's logical size was 32,481,280 bytes (31 MB), which matches the nearly empty databases. A `halfvec(768)` value is 1,536 bytes. At about 3,000 patches a slide, 200 slides are about 600,000 values and about 880 MB of raw vectors, before the HNSW graph and the heap. That is already over 512 MB. Report-chunk `vector(384)` rows are a few megabytes and do fit. The load into Lakebase has to be a measured subset that stays under 512 MB with its indexes. The rest can stay in local Postgres.

### Foundation models

`GET /api/2.0/serving-endpoints` returned 11 READY pay-per-token Foundation Model endpoints and no custom endpoints. None is Claude. Calls bill Databricks units under the fair-use quota, not the $50 Anthropic credit. Claude stays on `ANTHROPIC_API_KEY`.

| Endpoint | Task |
| --- | --- |
| `databricks-gpt-oss-120b`, `databricks-gpt-oss-20b` | chat |
| `databricks-qwen3-next-80b-a3b-instruct`, `databricks-qwen35-122b-a10b` | chat |
| `databricks-gemma-3-12b` | chat |
| `databricks-meta-llama-3-1-8b-instruct`, `databricks-meta-llama-3-3-70b-instruct` | chat |
| `databricks-llama-4-maverick` | chat |
| `databricks-gte-large-en`, `databricks-bge-large-en`, `databricks-qwen3-embedding-0-6b` | embeddings |

A call to `databricks-meta-llama-3-1-8b-instruct` (20 tokens) returned the word Pong, and a second call made it invoke a tool. `databricks-bge-large-en` returned a 1,024-dimensional vector. That space is separate from the 384-d report embeddings and the 768-d CONCH-Z embeddings, and the two are not compared.

### Apps and outbound HTTPS

The Apps API is enabled and listed zero apps. A one-off serverless notebook job (standard performance, environment version 2) then made outbound HTTPS and was deleted, along with its notebook and result file:

| Target | Result |
| --- | --- |
| `https://api.anthropic.com` | HTTP 404 from the host (the bare origin has no route; the connection was accepted) |
| `https://huggingface.co` | HTTP 200 |

So both hosts are on the trusted-domain list for serverless compute. The job is not an App process. The deploy issue still does one call from the App. MLflow accepted creating and deleting an experiment, which is the tracing API the consult agent needs.

The configured account host has a trailing slash. Clients strip it before joining an API path.

### What this changes for later work

- The Lakebase load keeps `SEARCH_BACKEND=pgvector`, uses that `raw` volume, and loads only a subset that fits in 512 MB with HNSW. It does not enable Lakebase Search and does not install `lakebase_vector`.
- Consult-agent tracing can use the Databricks MLflow tracking API on this account.
- The App keeps `LLM_PROVIDER=anthropic`. A Databricks chat endpoint is a different client and a different model, available if the App cannot reach Anthropic. Restart the App on Sunday morning.

## GPU compute

One rented datacenter GPU (Lambda A100 40 GB or equivalent) for slide download, tiling, embedding and export. The MacBook is for development and the 10-slide smoke test only. The same pipeline code handles a single slide for the live-ingestion feature.
