---
id: S-02
title: Case workspace and viewer
route: /cases/[caseId]
status: in-progress
priority: P0
features: [F-03, F-06, F-12]
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
| Case header | Case ID, patient (`display_label` and prior-case count badge linking to S-09, F-12.1), `specimen_label`, specialty, patient age and sex, status, assigned pathologist, ICD-10 (signed-out cases only). A way back to the worklist. |
| Slide list | The case's slides with thumbnail, stain and ingestion status. Shown only when the case has more than one slide. |
| Viewer | The deep-zoom image, navigator minimap, magnification readout, scale bar. Hosts the overlay layers. |
| Selection actions | Appears when a patch or region is selected: Find similar tissue, Ask about this region, Annotate. |
| Layer controls | Show or hide search hits and annotations. |
| Report-word overlay | When a target word is selected in S-03, shades patches by embedding similarity and names the active word. Carries the label that this is similarity, not a finding, and a clear control. |
| Panel switch | Report, Evidence, Consult, Annotations. One is open at a time, or none. |
| Side panel | The open panel: [S-03](S03-report-panel.md), [S-04](S04-evidence-panel.md), [S-05](S05-consult-panel.md) or [S-06](S06-annotations-panel.md). |

## Data

| Region | Route |
| --- | --- |
| Case header, slide list | `GET /api/cases/{id}` |
| Viewer | `GET /api/slides/{id}`, `GET /api/slides/{id}.dzi`, tile routes |
| Patch under a click | `GET /api/slides/{id}/patches/at?x=&y=` |
| Arriving at a patch | `GET /api/patches/{id}` when the URL names a patch rather than coordinates |
| Report-word overlay | `POST /api/slides/{id}/heatmap` |

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
| Select a report target word | Word-to-patch similarity is drawn and the active word is named (F-06.3, F-06.6). | `POST /api/slides/{id}/heatmap` |
| Clear report-word overlay | Shading and the active word are removed (F-06.7). | — |
| Toggle a layer | That layer hides or shows; others unchanged (F-03.8). | — |
| Switch panel | The chosen panel opens; `panel` set in the URL. | per panel |
| Select the patient in the header | Opens S-09 for this case's patient (F-12.1). | — |
| Hide panel | The side panel collapses so the viewer uses the available width; a persistent control restores it. | — |
| Copy link | The current URL, which reproduces the view (F-03.5). | — |

## States
- **Loading case** — header and viewer placeholders.
- **Case not found** — says so, with a link to the worklist.
- **Slide fetching** — the slide thumbnail with progress while the server caches the file (F-03.9).
- **Slide not ready** — the slide's ingestion status in place of the image (F-03.10).
- **Tile error** — failed tiles are retried; if the slide cannot be read at all, an error with retry replaces the viewer. The side panel keeps working.
- **Report-word overlay loading** — the selected word stays active while similarity is computed.
- **Report-word overlay error** — a message appears near the active-word label; the viewer is otherwise unaffected.
- **Open case** — the header shows the case as not yet reported and shows no ICD-10.

## Out of scope
- Two slides side by side.
- Image adjustment and measurement.
- More than one report-word overlay at once.
- Keyboard shortcuts beyond what the viewer provides by default.
