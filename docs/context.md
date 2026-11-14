# Context

Constraints the project works within: the hackathon, the track, the dataset, the model licences and the platform. Facts here were read from the sources linked on Sat 14 Nov 2026; items marked *unverified* have not been confirmed first-hand.

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

## Dataset: HistAI

[HistAI](https://github.com/HistAI/HISTAI) is an open collection of 112,801 whole slide images across 47,279 cases with pathology report text. It is used because it is openly downloadable and pairs slides with reports.

| Property | Value |
| --- | --- |
| Hosting | Hugging Face datasets under `histai/`, one repository per subset. Start from `histai/HISTAI-metadata`. |
| Licence | CC BY-NC 4.0, research use only |
| Format | Pyramidal `.tiff`, path `case_<case_id>/slide_<stain>_<n>.tiff` |
| Magnification | 20x for 110,338 slides; 40x for 2,463 |
| Stain | H&E 92,536; IHC 16,920; other 3,345 |
| Subsets | breast 1,925 slides · thorax 829 · colorectal-b1 5,379 · colorectal-b2 94 · gastrointestinal 202 · hematologic 214 · skin-b1 7,710 · skin-b2 43,757 · mixed 52,691 |
| Report fields | `diagnosis` (incoming clinical notes), `conclusion`, `diff_diagnosis`, `micro_protocol`, `grossing`, `additional_info`, `age`, `gender`, `icd10`, `specialization`, `case_mapping` |

### Known quality problems

From a published audit of the dataset (*unverified* first-hand; treat as checks for the cohort builder to enforce):

- Exact duplicate metadata entries exist. Deduplicate before sampling.
- Skin and gastrointestinal specimens dominate. Sample per specialty rather than uniformly.
- `specialization` is often empty. Fall back to the subset name.
- `diagnosis` is the incoming note, not the final answer. `conclusion` is the pathologist's result and is the primary text.
- Some `conclusion` fields hold molecular results or hedged wording. Exclude records with an empty or molecular-only conclusion.

### What the dataset does not have

**No report author.** HistAI does not identify the pathologist. The "who to consult" feature needs authorship, so pathologists are synthetic: a small seeded roster assigned to reports by specialty. This is disclosed in the README and in the app.

### Cohort

The app runs on a sample, sized to what one GPU and one evening can process.

| Tier | Slides | Purpose |
| --- | --- | --- |
| `smoke` | 10 | Proves the pipeline end to end before the full run. |
| `demo` | about 200, one H&E 20x slide per case, balanced across breast, thorax, colorectal, gastrointestinal, hematologic and skin | The submission. |
| `stretch` | 500 or more | Only if the demo tier is loaded and searchable with time to spare. |

About 10 demo cases are held out as open, unreported cases: their real reports are stored but hidden, so the worklist has cases to work on and retrieval quality can be measured.

## Model licences

| Model | Licence | Consequence |
| --- | --- | --- |
| CONCH-Z and CONCH v1.5 (MahmoodLab) | CC-BY-NC-ND 4.0, gated to institutional Hugging Face accounts | Non-commercial research only. Access is already approved for this team. Weights and derived features are never committed or redistributed. |
| BAAI/bge-small-en-v1.5 | MIT | No restriction. |

Virchow2 was the alternative considered. See [architecture.md](architecture.md#decisions) for why it was not chosen.

## Platform: Databricks Free Edition

From the [limitations page](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations):

| Limit | Effect on the design |
| --- | --- |
| Serverless compute only; no GPU serving, no custom models on GPU | Embeddings are computed off-platform on a rented GPU. Query-time text encoding runs on CPU in the app. |
| Outbound internet restricted to a set of trusted domains (list not published) | *Unverified* whether the Anthropic API is reachable from an App. The LLM provider is configurable and this is tested early. |
| One Lakebase project, scale to zero | One Postgres database for everything served. |
| Up to 3 Apps; each stops 24 hours after start or redeploy | Restart the App on Sunday morning before judging. |
| Apps are not publicly accessible | The demo runs from an authenticated browser session, or from the laptop. |
| No custom storage locations; daily fair-use compute quota | Files are pushed into a managed Unity Catalog Volume. Heavy compute stays off Databricks. |
| Non-commercial use only | Matches the dataset and model licences. |

Lakebase Search adds `lakebase_ann` and `lakebase_bm25` index types on top of pgvector. Enabling it cannot be undone and restarts compute, so the baseline is plain pgvector and `tsvector`.

## GPU compute

One rented datacenter GPU (Lambda A100 40 GB or equivalent) for slide download, tiling, embedding and export. The MacBook is for development and the 10-slide smoke test only. The same pipeline code handles a single slide for the live-ingestion feature.
