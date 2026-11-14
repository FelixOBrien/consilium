---
feature: F-06
title: Report-context similarity overlay
status: in-progress
---

# Stories · F-06 Report-context similarity overlay

Feature: [F-06](../features/F06-phrase-heatmaps.md)

## US-06.1 · Discover report words that map to tissue

As a Pathologist, I want informative report words to reveal themselves in context so that I can explore the wording without leaving the report or scanning a separate concept list.

- **Priority:** P1
- **Covers:** F-06.1, F-06.2, F-06.8
- **Acceptance:**
  - Given report context, when I hover or focus an eligible content word, then it reveals that it can be mapped.
  - Given a stop word or punctuation, when I hover it, then it remains ordinary report text.
  - Given the report panel, then no curated concept list or free-text heatmap input is present.

## US-06.2 · Map a report word onto the slide

As a Pathologist, I want to select an informative report word and see matching slide regions so that I can connect the language already in the case context to tissue worth examining.

- **Priority:** P1
- **Covers:** F-06.3, F-06.4, F-06.5, F-06.6
- **Acceptance:**
  - Given an eligible target word, when I select it, then within 2 seconds the slide is shaded by word-to-patch similarity.
  - Given an active overlay, then the viewer names the selected word and labels the shading as embedding similarity, not a finding.
  - Given the overlay, then there are no threshold or opacity controls.

## US-06.3 · Switch or clear the active report word

As a Pathologist, I want to replace or clear the active report word so that the viewer only shows the context I am currently checking.

- **Priority:** P1
- **Covers:** F-06.7
- **Acceptance:**
  - Given an active report word, when I select a different target word, then the overlay is replaced.
  - Given an active report word, when I clear it from the report or viewer, then the shading is removed.

## US-06.4 · Shade the slide from selected tissue

As a Pathologist, I want the open slide shaded by similarity to a patch or region I selected, with the connected similar tissue returned, so that I can see whether the tissue I am examining continues nearby.

- **Priority:** P2
- **Covers:** F-06.9, F-06.10, F-06.11, F-06.12
- **Acceptance:**
  - Given a patch on the open slide, when I request a heatmap for that patch, then that patch scores 1.0 and the notice says the shading is embedding similarity to the selected tissue, not a finding and not a diagnosis.
  - Given a region on the open slide, when I request a heatmap with `grow`, then every seed patch is inside the cluster, the cluster is 8-connected, and its bounding box encloses every cell.
  - Given a patch or region heatmap with `grow` false, then the response has scores and no cluster.
  - Given a request with no source or more than one source, a patch or region from another slide, negative text with a patch or region, or `grow` with a report word or concept, then the API rejects it.
  - Given a report word or concept heatmap, then the response matches the report-word contract apart from `source`.
