---
id: S-10
title: Slide compare
route: /compare
status: done
priority: P2
features: [F-03]
stories: [US-03.5]
figma: ""
linear: [SKO-290]
---

# S-10 · Slide compare

## Purpose
The pathologist puts the open case's slide next to a precedent slide and moves them together at the same physical scale, to check retrieved tissue against the slide they are reading. The view retrieves and aligns precedent. It does not state a diagnosis.

## Entry points
- A shared or copied `/compare` URL with `left` and `right` slide ids, and optional level-0 viewports.
- From [S-04](S04-evidence-panel.md), once that panel exists: a compare action builds the URL in the register below. S-04 does not link here yet.

## Regions

| Region | Contains |
| --- | --- |
| Compare bar | A statement that the right pane is precedent tissue for comparison and does not assign a diagnosis. A control that links or unlinks pan and zoom. |
| Open-case pane | Labelled as the open case. Case id, specimen label when the case summary loads, slide ordinal, stain, magnification and microns per pixel. The current microns per screen pixel. The deep-zoom image, navigator, and an Open case link. A locus mark when the URL gave `lx` and `ly`. |
| Precedent pane | Labelled as precedent. The same fields as the open-case pane for the other slide. A locus mark when the URL gave `rx` and `ry`. |

## Data

| Region | Route |
| --- | --- |
| Both pane headers | `GET /api/slides/{id}`, then `GET /api/cases/{case_id}` for the specimen label |
| Both viewers | `GET /api/slides/{id}.dzi` and the tile routes |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Open a URL with `left` and `right` | Both slides load. `lx`, `ly`, `lzoom` and `rx`, `ry`, `rzoom` restore each viewport in level-0 pixels (F-03.5). `sync` defaults to linked. | `GET /api/slides/{id}` |
| Pan or zoom one pane while linked | The other pane moves by the same physical distance, and both panes show the same microns per screen pixel from each slide's `mpp` (F-03.2, US-03.5). | tile routes |
| Pan or zoom while linked, with either `mpp` missing | Zoom is matched relatively and each pane header says so (US-03.5). | tile routes |
| Unlink, align by hand, link again | Linking turns off so each pane moves alone, then turns on from the new centres. The right pane adopts the left pane's physical scale without jumping either centre (US-03.5). | — |
| Stop moving | `lx`, `ly`, `lzoom`, `rx`, `ry`, `rzoom` and `sync` are written back to the URL after movement finishes, and a reload restores them (F-03.5). | — |
| Open case | Opens [S-02](S02-case-workspace.md) for that pane's case with `slide`, `x`, `y` and `zoom` (F-03.5). <!-- pragma: allowlist secret --> | — |

## States
- **Loading** — the pane says the slide is loading. The other pane is independent.
- **Missing parameters** — neither viewer opens. The page names the URL it needs: `/compare?left=<slideId>&right=<slideId>`.
- **Slide not found** — that pane says the slide was not found. The other pane keeps working.
- **Slide not ready** — that pane shows the slide status in place of the image (`409` `not_ready` on the tile routes, or a status other than `ready` on `GET /api/slides/{id}`). The other pane keeps working.
- **Tile error** — that pane says the tiles failed and offers retry. The other pane keeps working.
- **Research notice** — the notice on every screen stays visible.

## Out of scope
- A compare action on an evidence hit (named in the pull request for [S-04](S04-evidence-panel.md); this screen only defines the URL).
- Overlays, annotations, heatmaps, and more than two panes.
- Stating or implying that the two slides share a diagnosis.
