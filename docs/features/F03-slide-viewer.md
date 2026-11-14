---
id: F-03
title: Slide viewer
status: planned
priority: P0
stories: [US-03.1, US-03.2, US-03.3, US-03.4]
models: [case, slide, patch]
screens: [S-02]
depends_on: [F-01, F-09]
linear: [SKO-265, SKO-270]
---

# F-03 · Slide viewer

## Summary
A pathologist opens a case and views its whole slide images: panning and zooming from the whole slide to cellular detail, switching between the case's slides, and selecting a patch of tissue to act on.

## Why
G1. The slide is the primary evidence. Every retrieval feature starts from, or returns to, a location on a slide.

## Scope
**In**
- Deep zoom viewing of one slide at a time.
- A URL that addresses a slide and a location.
- Patch selection.
- Hosting overlays drawn by other features.

**Out**
- Side-by-side comparison of two slides (P2, noted in [S-04](../screens/S04-evidence-panel.md)).
- Image adjustments such as brightness or stain normalisation.
- Measurement tools.

## Behaviour
1. Opening a case shows its first slide fitted to the viewport. A case with several slides lists them with thumbnail and stain; selecting one switches the viewer.
2. The viewer pans and zooms continuously between the fitted view and the slide's native resolution (`slide.magnification`).
3. Tiles are served in Deep Zoom format from the original pyramidal file. All coordinates exchanged with the API are level-0 pixels of that file.
4. The viewer shows the current magnification, a scale bar computed from `slide.mpp`, and a navigator minimap.
5. The URL holds `slide`, `x`, `y` and `zoom`. Loading a URL with these restores the view. Other features link to a location by building this URL.
6. Clicking tissue selects the patch containing that point, found from `patch.x`, `patch.y`, `patch.size`. The selected patch is outlined. Clicking glass with no patch clears the selection.
7. Dragging on the slide with the region tool selects a rectangle. A selected patch or rectangle offers **Find similar tissue** ([F-05](F05-evidence-search.md)), **Ask about this region** ([F-07](F07-consult-agent.md)) and **Annotate** ([F-08](F08-annotations.md)).
8. Overlay layers stack in this order above the image: heatmap ([F-06](F06-phrase-heatmaps.md)), search-hit markers ([F-05](F05-evidence-search.md)), annotations ([F-08](F08-annotations.md)), selection. Each can be shown or hidden independently.
9. If the slide file is not yet in the server cache, the first request fetches it. The viewer shows progress and the slide thumbnail until tiles arrive.
10. A slide whose ingestion is not complete shows its status in place of the image.

## API
- `GET /api/slides/{id}` — slide metadata: dimensions, mpp, magnification, stain, patch size, status.
- `GET /api/slides/{id}.dzi` — Deep Zoom descriptor.
- `GET /api/slides/{id}_files/{level}/{col}_{row}.jpeg` — a tile.
- `GET /api/slides/{id}/thumbnail` — whole-slide thumbnail.
- `GET /api/slides/{id}/patches/at?x=&y=` — the patch containing a level-0 point, or 404.
- `GET /api/patches/{id}` — a patch's slide and coordinates.
- `GET /api/patches/{id}/thumbnail` — the patch image.

## Acceptance
- A demo slide opens and zooms to native resolution with no missing tiles.
- Copying the URL at a zoomed location and opening it in a new tab shows the same location.
- Clicking tissue outlines exactly one patch; the outline matches the patch's stored coordinates.
- Switching slides within a multi-slide case changes the image and the URL.

## Open questions
- Whether every sampled TCGA `.svs` file carries `openslide.mpp-x` (`aperio.MPP`) and `openslide.objective-power` (`aperio.AppMag`). If not, `slide.mpp` is supplied through TRIDENT's slide list or the slide is excluded by the manifest.
