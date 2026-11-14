---
feature: F-08
title: Annotations
status: planned
---

# Stories · F-08 Annotations

Feature: [F-08](../features/F08-annotations.md)

## US-08.1 · Mark a region

As a Pathologist, I want to draw a region on a slide and label it so that I have a record of what I found and where.

- **Priority:** P1
- **Covers:** F-08.1, F-08.2, F-08.5, F-08.7
- **Acceptance:**
  - Given an open slide, when I draw a rectangle and give it a label, then it appears on the slide and in the annotation list.
  - Given a saved annotation, when I reload and zoom in or out, then it stays on the same tissue.
  - Given the list, when I select an annotation, then the viewer moves to it.

## US-08.2 · Show a colleague what I mean

As a Pathologist, I want my annotations to be visible to others who open the case so that a colleague sees exactly the tissue I am asking about.

- **Priority:** P1
- **Covers:** F-08.3, F-08.4, F-08.8
- **Acceptance:**
  - Given an annotation I made, when another pathologist opens the slide, then they see it with my name and cannot edit or delete it.
  - Given my own annotation, when I delete it, then I am asked to confirm first.

## US-08.3 · Search from an annotation

As a Pathologist, I want to search for tissue similar to an annotated region, or ask the agent about it, so that marking a region leads directly to evidence.

- **Priority:** P1
- **Covers:** F-08.6
- **Acceptance:**
  - Given a rectangle annotation, when I choose Find similar tissue, then evidence results for that region appear.
  - Given a rectangle annotation, when I choose Ask about this region, then the consult input has the region attached.
