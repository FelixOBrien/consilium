---
id: S-02
title: Case workspace and viewer
route: /cases/[caseId]
status: planned
priority: P0
features: [F-03, F-06]
stories: [US-03.1, US-03.2, US-03.3, US-03.4, US-06.1, US-06.2, US-06.3]
figma: ""
linear: [SKO-270, SKO-275]
---

# S-02 · Case workspace and viewer

## Purpose
The pathologist works on one case here: examining its slide, with one side panel open for the report, evidence, consult or annotations. This is the screen the demo happens on.

## Entry points
- Selecting a case in S-01 or S-07: arrives at the first slide, fitted, with the report panel open.
- Opening a search result, citation or shared link: arrives with `slide`, `x`, `y`, `zoom` set, centred on a location, with that patch marked.
- A finished ingestion job in S-08.

## Regions

| Region | Contains |
| --- | --- |
| Case header | Case ID, specialty, patient age and sex, status, assigned pathologist, ICD-10 (signed-out cases only). A way back to the worklist. |
| Slide list | The case's slides with thumbnail, stain and ingestion status. Shown only when the case has more than one slide. |
| Viewer | The deep-zoom image, navigator minimap, magnification readout, scale bar. Hosts the overlay layers. |
| Selection actions | Appears when a patch or region is selected: Find similar tissue, Ask about this region, Annotate. |
| Layer controls | Show or hide each layer: heatmap, search hits, annotations. |
| Heatmap controls | Concept chips for the case's specialty, a free-text phrase input with optional negative phrase, threshold and opacity, the list of top regions, a clear control, and the label that this is similarity to the phrase, not a finding. |
| Panel switch | Report, Evidence, Consult, Annotations. One is open at a time, or none. |
| Side panel | The open panel: [S-03](S03-report-panel.md), [S-04](S04-evidence-panel.md), [S-05](S05-consult-panel.md) or [S-06](S06-annotations-panel.md). |

## Data

| Region | Route |
| --- | --- |
| Case header, slide list | `GET /api/cases/{id}` |
| Viewer | `GET /api/slides/{id}`, `GET /api/slides/{id}.dzi`, tile routes |
| Patch under a click | `GET /api/slides/{id}/patches/at?x=&y=` |
| Arriving at a patch | `GET /api/patches/{id}` when the URL names a patch rather than coordinates |
| Concept chips | `GET /api/concepts?specialty=` |
| Heatmap | `POST /api/slides/{id}/heatmap` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Pan or zoom | View changes; `x`, `y`, `zoom` update in the URL after movement stops (F-03.2, F-03.5). | tile routes |
| Select another slide | Viewer switches; `slide` set in the URL; selection and heatmap cleared (F-03.1). | `GET /api/slides/{id}` |
| Click tissue | The patch under the click is outlined; selection actions appear (F-03.6). | `GET /api/slides/{id}/patches/at` |
| Click glass | Selection cleared (F-03.6). | — |
| Drag a region | A rectangle is selected; selection actions appear. | — |
| Find similar tissue | Evidence panel opens and runs a patch or region query (F-03.7, F-05 Q1, Q2). | `POST /api/search/patches` |
| Ask about this region | Consult panel opens with the region attached (F-07.9). | — |
| Annotate | Annotations panel opens with the region ready to label (F-08.1). | — |
| Click a concept chip | Heatmap for that concept is drawn (F-06.1, F-06.7). | `POST /api/slides/{id}/heatmap` |
| Submit a phrase | Heatmap for that phrase is drawn; a truncation notice shows if returned (F-06.8). | `POST /api/slides/{id}/heatmap` |
| Change threshold or opacity | Shading updates without a request (F-06.5). | — |
| Select a top region | Viewer moves to that patch (F-06.6). | — |
| Clear heatmap | Shading removed (F-06.11). | — |
| Toggle a layer | That layer hides or shows; others unchanged (F-03.8). | — |
| Switch panel | The chosen panel opens; `panel` set in the URL. | per panel |
| Copy link | The current URL, which reproduces the view (F-03.5). | — |

## States
- **Loading case** — header and viewer placeholders.
- **Case not found** — says so, with a link to the worklist.
- **Slide fetching** — the slide thumbnail with progress while the server caches the file (F-03.9).
- **Slide not ready** — the slide's ingestion status in place of the image (F-03.10).
- **Tile error** — failed tiles are retried; if the slide cannot be read at all, an error with retry replaces the viewer. The side panel keeps working.
- **Heatmap loading** — chips and input disabled while a heatmap is computed; the previous heatmap stays until the new one arrives.
- **Heatmap error** — a message near the heatmap controls; the viewer is unaffected.
- **Open case** — the header shows the case as not yet reported and shows no ICD-10.

## Out of scope
- Two slides side by side.
- Image adjustment and measurement.
- More than one heatmap at once.
- Keyboard shortcuts beyond what the viewer provides by default.
