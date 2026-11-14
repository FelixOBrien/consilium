# Consilium — Histopathology Vector Application

*Consilium* is the working name: in medicine, a consilium is a meeting of doctors convened to decide a difficult case.

## Problem

Histopathology is the study of tissue samples under a microscope. It is a key tool in the diagnosis of diseases, being the gold standard for many diseases such as cancer. It is a time-consuming and expensive process, and requires pathologists who are doctors with years of training and experience. Often, there is significant collaboration amongst pathologists to diagnose a single case, particularly in the case of rare diseases and given the tendency for diagnoses to result in high-cost and high-risk treatments such as chemotherapy and surgery.

Whilst there are significant current capabilities to do with Machine Learning and AI in the field of Histopathology, deploying these capabilities is a difficult task. The main challenges are:
- Licensing issues with frontier AI models
- Concerns over diagnostic accuracy of AI models
- Complexity of Whole Slide Images (WSI)

Outside of pathology and medicine broadly, the deployment of Retrieval-Augmented Generation (RAG) models, agents and LLMs broadly is commonplace. The question we are looking to address is how can we take these capabilities and apply them to the field of Histopathology?

## Approach

We shift the focus from deploying AI models for diagnostic purposes to treating Histopathology as an **information retrieval task**, where we can use the power of LLMs to help pathologists diagnose cases. The model never says what the diagnosis is. It finds the tissue, the reports and the colleagues that are relevant, and the pathologist decides.

## Goals

| # | Goal | What it means in the product |
| --- | --- | --- |
| G1 | Reduce time-to-diagnosis within a case | From an open slide, relevant precedent is one click or one sentence away. |
| G2 | Reduce back-and-forth collaboration between pathologists | The system names the colleague who has reported the most similar cases, with the evidence, so the first consult request goes to the right person. |
| G3 | Help pathologists gain personal confidence in their diagnoses | Every result is a real prior case with its slide region and signed report, so the pathologist checks their impression against precedent rather than against a model score. |

## Non-goals

- Producing, suggesting or scoring a diagnosis for the open case.
- Clinical deployment, regulatory compliance or handling patient-identifiable data.
- Replacing a laboratory information system. Accessioning, billing and sign-out workflow are out of scope.
- Training or fine-tuning a pathology model.

## Solution

We build an application that facilitates basic pathologist workflows:
- Viewing a worklist of cases and searching it
- Reviewing a patient's longitudinal history across multiple cases
- Viewing the whole slide images for a case
- Viewing the report for a case
- Annotating a slide
- Ingesting a new slide

We augment this with vector search and agent capabilities:
- Vector search over slide patches and reports, across the corpus or scoped to a single patient, to find relevant tissue and relevant cases
- An agent that reviews the patient's previous cases, searches corpus precedent, reads the reports it finds and summarises them, including who would be best to consult
- Heatmaps that map a phrase from a report onto the regions of the slide it describes

Producing and sharing reports between pathologists is part of the longer-term product but is not built for the hackathon. The feature register in [features/index.md](features/index.md) is the authoritative scope.

## Success

The hackathon demo succeeds if, live and without a script failure, a judge sees:

1. A case opened from the worklist with its slide zooming smoothly to cellular detail.
2. A region of tissue selected and visually similar regions from other cases returned, each linked to its signed report.
3. A free-text description returning matching tissue patches that the report text alone would not find.
4. The consult agent answering "who should I consult on this case?" with named pathologists, counts and cited cases.
5. The same data flowing through a Databricks pipeline into the store the app queries.

Measured check: for held-out cases, the share of top-5 retrieved cases matching the held-out case's withheld ICD-O-3 morphology group and ICD-10 category, reported for morphology search and report search (see [F-10](features/F10-retrieval-evaluation.md)).

## Tech stack

Chosen for a hackathon MVP as outlined in [context.md](context.md). Detail and rationale are in [architecture.md](architecture.md).

### Design
Figma for screen design. This also qualifies the project for the Figma Best-Designed AI Product prize.

### Backend infrastructure
Databricks Free Edition: Unity Catalog Volumes for files, Delta tables for the lakehouse, Lakebase (Postgres with pgvector) for serving and search, Databricks Apps for hosting. A Python FastAPI service is the single backend.

### Frontend
TypeScript with SvelteKit, built as a static app and served by the API. shadcn-svelte for mapping Figma designs to code. OpenSeadragon for slide viewing.

### ML
CONCH-Z for patch and image-query text embeddings, chosen over Virchow2 because it aligns images and text without training. TRIDENT for tiling and feature extraction on a rented GPU. A small general text embedding model for reports.

### Agents
Claude through the Anthropic API, with the retrieval functions exposed as tools.
