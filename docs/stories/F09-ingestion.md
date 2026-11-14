---
feature: F-09
title: Ingestion
status: planned
---

# Stories · F-09 Ingestion

Feature: [F-09](../features/F09-ingestion.md)

## US-09.1 · Build a clean cohort

As a Data operator, I want to build a balanced, de-duplicated list of diagnostic slides and paired reports from TCGA so that search results are not dominated by one organ or stalled by multi-gigabyte files.

- **Priority:** P0
- **Covers:** F-09.1, F-09.2
- **Acceptance:**
  - Given GDC slide and case metadata and `TCGA_Reports.csv`, when I build the demo tier, then the manifest has one open diagnostic H&E `.svs` slide under the size cap per case, no duplicate cases, a paired non-empty report and primary diagnosis for every case, and equal case counts per specialty where available.
  - Given the same seed, when I rebuild, then I get the same manifest.
  - Given the manifest, when I count held-out cases, then there are about 10, spread across specialties.

## US-09.2 · Run the pipeline and trust it to finish

As a Data operator, I want one command to take a manifest through to loaded, indexed data, resuming after failure, so that a long run does not have to start again.

- **Priority:** P0
- **Covers:** F-09.3, F-09.4, F-09.5, F-09.6, F-09.7, F-09.8, F-09.9, F-09.13
- **Acceptance:**
  - Given the smoke manifest, when I run the pipeline, then 10 cases appear in the worklist with slides that open and search that returns results.
  - Given a run interrupted part-way, when I run it again, then completed slides are skipped.
  - Given one slide that fails, when the run ends, then the failure is listed and every other slide is loaded.
  - Given a finished run, when I read its output, then I see counts of slides, patches, reports, chunks and failures.

## US-09.3 · Land the data in the lakehouse

As a Data operator, I want the same data in Delta tables and in Lakebase so that the app's store is produced by a Databricks pipeline and can be rebuilt from it.

- **Priority:** P0
- **Covers:** F-09 stage 10, F-09.9
- **Acceptance:**
  - Given parquet files in the Volume, when I run the Databricks notebook, then bronze, silver and gold tables exist for each pipeline model.
  - Given the full export, when I compare row counts, then parquet and Delta gold agree.
  - Given `consilium.pipeline subset` and `consilium.pipeline load` of that subset, when I compare row counts, then Lakebase agrees with the subset. `consilium.pipeline reconcile --subset-from` checks both. <!-- pragma: allowlist secret -->

## US-09.4 · Ingest one new slide and watch it arrive

As a Data operator, I want to queue a single slide and see it move through each stage so that I can add a case and show that ingestion is live.

- **Priority:** P2
- **Covers:** F-09.10, F-09.11, F-09.12
- **Acceptance:**
  - Given a TCGA project and GDC slide file name or ID, when I queue it, then a job appears as queued and then advances through its stages.
  - Given a job that reaches done, when I open the case, then the slide opens and is searchable without restarting anything.
  - Given a job that fails, when I view it, then I see the stage and error and can retry it.
