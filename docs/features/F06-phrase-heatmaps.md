---
id: F-06
title: Report-context similarity overlay
status: planned
priority: P1
stories: [US-06.1, US-06.2, US-06.3]
models: [patch, slide, concept]
screens: [S-02, S-03]
depends_on: [F-03, F-04]
linear: [SKO-267, SKO-275]
---

# F-06 · Report-context similarity overlay

## Summary
A pathologist explores the words already present in the case context or report. Informative target words reveal themselves on hover; selecting one shades the open slide by how closely each patch matches that word's embedding.

## Why
G1 and G3. It turns a sentence in a report into places to look, and lets the pathologist check that a phrase and a region agree.

## Scope
**In**
- One word-to-patch similarity overlay on the open slide.
- Target words from the report context.

**Out**
- Model attention maps. The heatmap is embedding similarity between phrase and patch, and the UI says so.
- A curated phrase list, free-text phrase input or negative phrase.
- Threshold and opacity controls.
- Precomputed overlays.
- Several words overlaid at once.

## Behaviour
1. Eligible target words are informative report terms, excluding stop words and punctuation.
2. Target words use a subtle hover and focus state; ordinary words remain plain report text.
3. Selecting a target word encodes that word with the CONCH-Z text tower. Each patch of the open slide is scored by cosine similarity between `patch.embedding` and the word vector.
4. Scores are min-max normalised across the slide to 0–1 before they are returned.
5. The viewer shades patches by score using a fixed visual scale. There are no user-facing threshold or opacity controls.
6. The active overlay names the selected report word and carries the label that this is embedding similarity, not a finding.
7. Selecting another target word replaces the active overlay. The active word can be cleared from the report or viewer.
8. The report remains readable and selectable; embedding targets do not appear as a separate list.

## API
- `POST /api/slides/{id}/heatmap` — body: `text` containing the selected target word. Returns per-patch scores.

## Acceptance
- Hovering an eligible report word reveals that it can be mapped; stop words do not become targets.
- Selecting a target word shades the slide within 2 seconds on a demo slide.
- The viewer names the active word and states that the overlay is similarity, not a finding.
- Clearing the active word removes the overlay.

## Open questions
- How eligible target words and their display threshold are represented in the report API contract.
