---
feature: F-03
title: Slide viewer
status: done
---

# Stories · F-03 Slide viewer

Feature: [F-03](../features/F03-slide-viewer.md)

## US-03.1 · Examine a slide

As a Pathologist, I want to pan and zoom a case's slide from the whole section down to cells so that I can examine the tissue as I would under a microscope.

- **Priority:** P0
- **Covers:** F-03.1, F-03.2, F-03.3, F-03.4, F-03.9
- **Acceptance:**
  - Given a case, when I open it, then its first slide is shown fitted to the view.
  - Given the slide, when I zoom to the maximum, then I see native-resolution tissue with no missing tiles, and the magnification and scale bar update.
  - Given a slide not yet cached on the server, when I open it, then I see its thumbnail and progress until tiles arrive.

## US-03.2 · Switch between a case's slides

As a Pathologist, I want to switch between the slides of a case so that I can review every section taken from the specimen.

- **Priority:** P1
- **Covers:** F-03.1, F-03.10
- **Acceptance:**
  - Given a case with more than one slide, when I select another slide, then the viewer shows it and the URL names it.
  - Given a slide still being ingested, when I select it, then I see its ingestion status instead of an image.

## US-03.3 · Return to an exact location

As a Pathologist, I want a link that reopens a slide at an exact location and zoom so that I, or a colleague, can come back to the same tissue.

- **Priority:** P0
- **Covers:** F-03.5
- **Acceptance:**
  - Given I am zoomed in on a region, when I copy the URL and open it in a new tab, then the same slide, region and zoom are shown.

## US-03.4 · Point at tissue

As a Pathologist, I want to select a piece of tissue by clicking it so that I can ask the system about exactly that tissue.

- **Priority:** P0
- **Covers:** F-03.6, F-03.7, F-03.8
- **Acceptance:**
  - Given tissue under the cursor, when I click, then one patch is outlined and Find similar tissue is offered.
  - Given a selection, when I click on empty glass, then the selection clears.
  - Given overlays are present, when I hide one layer, then the others stay visible.

## US-03.5 · Compare two slides at the same scale

As a Pathologist, I want to view the open case and a precedent slide side by side at the same physical scale so that I can check retrieved tissue against the slide I am reading.

- **Priority:** P2
- **Covers:** F-03.2, F-03.5
- **Acceptance:**
  - Given two ready slides, when I open `/compare?left=<slide id>&right=<slide id>`, then both slides are shown, the left pane is labelled as the open case, the right pane is labelled as precedent, and the research notice stays visible.
  - Given linked pan and zoom, when I pan or zoom one pane, then the other pane moves by the same physical distance and both panes show the same microns per screen pixel, using each slide's `mpp`.
  - Given either slide has no `mpp`, when the panes are linked, then zoom is matched relatively and the pane header says so.
  - Given the panes are linked, when I turn linking off, align them by hand, and turn linking on, then later movement stays linked from that alignment.
  - Given a viewport in the URL, when I reload, then both panes return to the stored level-0 location and zoom.
  - Given one slide id is missing, not found, or not ready, when the page opens, then that pane shows the failure and the other pane still works.
  - Given the two panes, when I read the copy, then nothing states or implies that the slides share a diagnosis.
