---
id: S-06
title: Annotations panel
route: panel in S-02 (panel=annotations)
status: planned
priority: P1
features: [F-08]
stories: [US-08.1, US-08.2, US-08.3]
figma: ""
linear: [SKO-283]
---

# S-06 · Annotations panel

## Purpose
The pathologist marks regions of the open slide, labels them, and uses them as the starting point for search or a consult question.

## Entry points
- The Annotations entry in the S-02 panel switch.
- Annotate, from a selected patch or region in the viewer: opens with that region ready to label.
- Selecting an annotation drawn on the viewer.

## Regions

| Region | Contains |
| --- | --- |
| Drawing tools | Rectangle and point. Choosing one puts the viewer in drawing mode until a shape is placed or drawing is cancelled. |
| Annotation form | For a new or selected annotation: label (required), note (optional), save, cancel. |
| Annotation list | The open slide's annotations, newest first: label, start of the note, author, time, kind. The acting pathologist's own are distinguishable from others'. |
| Annotation actions | Per annotation: go to, Find similar tissue and Ask about this region (rectangles only), and for the author, edit and delete. |
| Layer toggle | Show or hide all annotations on the viewer (F-08.7). |

## Data

| Region | Route |
| --- | --- |
| Annotation list and viewer layer | `GET /api/slides/{id}/annotations` |

## Actions

| Action | Result | API |
| --- | --- | --- |
| Choose a drawing tool, then draw | A shape appears on the viewer and the form opens (F-08.1). | — |
| Save a new annotation | It is stored in level-0 coordinates and appears in the list and on the viewer (F-08.2). | `POST /api/slides/{id}/annotations` |
| Cancel | The unsaved shape is removed. | — |
| Select an annotation | Viewer moves to it and it is highlighted (F-08.5). | — |
| Edit label, note or shape | Changes saved; author only (F-08.4). | `PATCH /api/annotations/{id}` |
| Delete | Asks for confirmation, then removes it; author only (F-08.8). | `DELETE /api/annotations/{id}` |
| Find similar tissue | Evidence panel opens and runs a region query for the rectangle (F-08.6). | `POST /api/search/patches` |
| Ask about this region | Consult panel opens with the rectangle attached (F-08.6). | — |
| Toggle layer | Annotations hide or show on the viewer; the list is unchanged. | — |

## States
- **Loading** — list placeholders; the viewer shows no annotations until loaded.
- **Empty** — says there are no annotations on this slide and how to draw one.
- **Drawing** — the viewer does not select patches or pan by drag until the shape is placed or cancelled.
- **Not the author** — edit and delete are absent for other pathologists' annotations.
- **Save error** — the form stays open with the message and the shape is kept so it can be retried.
- **Switching slide** — the list and layer change to the newly selected slide.

## Out of scope
- Polygon and freehand shapes.
- Replies or comments on an annotation.
- Annotations spanning more than one slide.
