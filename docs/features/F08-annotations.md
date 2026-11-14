---
id: F-08
title: Annotations
status: planned
priority: P1
stories: [US-08.1, US-08.2, US-08.3]
models: [annotation, slide, pathologist]
screens: [S-06]
depends_on: [F-03]
linear: [SKO-268, SKO-283]
---

# F-08 · Annotations

## Summary
A pathologist marks a region of a slide, labels it and adds a note. Annotations stay with the slide, are visible to anyone who opens the case, and can be used as a search query.

## Why
G2. An annotation points a colleague at exactly the tissue in question, which is most of what a consult conversation has to establish.

## Scope
**In**
- Rectangle and point annotations with a label and note.
- Listing, editing and deleting.
- Searching from an annotation.

**Out**
- Freehand and polygon shapes (P2).
- Comment threads on annotations.
- Measurements.

## Behaviour
1. The pathologist draws a rectangle or places a point on the open slide, then gives it a label and an optional note.
2. Geometry is stored in level-0 pixel coordinates (`annotation.geometry`), so it is independent of zoom.
3. Annotations on a slide are visible to every acting pathologist, each showing its author and creation time.
4. Only the author can edit or delete an annotation.
5. The annotations of the open slide are listed; selecting one moves the viewer to it.
6. A rectangle annotation offers **Find similar tissue**, which runs a region query ([F-05](F05-evidence-search.md) Q2), and **Ask about this region**, which attaches it to a consult question ([F-07](F07-consult-agent.md) rule 9).
7. Annotations can be hidden and shown as a layer without deleting them.
8. Deleting asks for confirmation.

## API
- `GET /api/slides/{id}/annotations` — annotations on a slide.
- `POST /api/slides/{id}/annotations` — create.
- `PATCH /api/annotations/{id}` — change label, note or geometry. Author only.
- `DELETE /api/annotations/{id}` — author only.

## Acceptance
- A drawn rectangle persists across reload at the same tissue location at any zoom.
- A second acting pathologist sees the annotation but cannot edit it.
- Find similar tissue from a rectangle returns evidence results.

## Open questions
None.
