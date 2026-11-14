---
id: S-08
title: Ingestion
route: /ingest
status: planned
priority: P2
features: [F-09]
stories: [US-09.4]
figma: ""
linear: [SKO-284]
---

# S-08 · Ingestion

## Purpose
The data operator queues one new slide and watches it move through the pipeline until it is searchable. In the demo, this shows ingestion is live.

## Entry points
- Ingest in the global bar.
- The no-data state of S-01.

## Regions

| Region | Contains |
| --- | --- |
| New job form | HistAI dataset (chosen from the known subsets) and slide path within it. Submit. |
| Corpus summary | Counts of cases, slides, patches and report chunks currently loaded. |
| Job list | Recent jobs, newest first: dataset and path, who queued it, status, current stage, started and finished times. |
| Job detail | For the selected job: each stage in order with its state, start and finish times and detail line; counts of patches and chunks once known; the error when failed. |

## Data

| Region | Route |
| --- | --- |
| Job list | `GET /api/ingestion/jobs`, re-requested every few seconds while any job is queued or running |
| Job detail | `GET /api/ingestion/jobs/{id}`, re-requested while that job is running |
| Corpus summary | `GET /api/health`, which reports table counts |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Submit the form | A queued job appears at the top of the list (F-09.10). | `POST /api/ingestion/jobs` |
| Select a job | Its detail is shown. | `GET /api/ingestion/jobs/{id}` |
| Retry a failed job | The job returns to queued, keeping its history (F-09.11). | `POST /api/ingestion/jobs` with the same dataset and path |
| Open case, on a finished job | Navigates to S-02 for the new case (F-09.12). | — |

## States
- **No jobs** — says nothing has been queued and explains what a job needs.
- **Queued with no worker** — if a job has been queued for more than a minute, says no worker appears to be running.
- **Running** — the current stage is marked active; completed stages show their duration.
- **Done** — counts shown and Open case offered.
- **Failed** — the failing stage and error shown, with retry.
- **Duplicate** — submitting a slide that already has an active job shows the existing job instead of creating another.
- **Already ingested** — submitting a slide that is already ready says so and offers Open case.
- **Error** — list could not be loaded, with retry.

## Out of scope
- Uploading a slide file from the browser.
- Bulk ingestion, which is run from the command line.
- Cancelling a running job.
- Deleting ingested data.
