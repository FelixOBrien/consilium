---
feature: F-06
title: Phrase heatmaps
status: planned
---

# Stories · F-06 Phrase heatmaps

Feature: [F-06](../features/F06-phrase-heatmaps.md)

## US-06.1 · See where a concept appears on the slide

As a Pathologist, I want to pick a histological concept and see the slide shaded by how well each region matches it so that I can go straight to the regions worth examining.

- **Priority:** P1
- **Covers:** F-06.1, F-06.2, F-06.3, F-06.5, F-06.7, F-06.10, F-06.11
- **Acceptance:**
  - Given an open slide, when I click a concept chip, then within 2 seconds the slide is shaded and labelled as similarity to the phrase, not a finding.
  - Given a heatmap, when I raise the threshold, then less of the slide is shaded; when I clear it, the shading is removed.
  - Given a case of one specialty, when I view the chips, then I see that specialty's concepts and the general ones.

## US-06.2 · Jump to the strongest regions

As a Pathologist, I want a list of the regions that match a phrase most strongly so that I can review them one by one instead of hunting across the slide.

- **Priority:** P1
- **Covers:** F-06.4, F-06.6
- **Acceptance:**
  - Given a heatmap, when I select an entry in the top-regions list, then the viewer moves to that region and it is among the most strongly shaded.

## US-06.3 · Map my own words or a report's words onto the slide

As a Pathologist, I want to type any phrase, or select one in a report, and see it on the slide so that I can check whether a described finding matches a region.

- **Priority:** P1
- **Covers:** F-06.8, F-06.9
- **Acceptance:**
  - Given free text, when I submit it, then a heatmap for that text appears.
  - Given a phrase selected in a report, when I choose Show on slide, then the heatmap appears without retyping.
  - Given text longer than the limit, when I submit it, then I am told it was truncated.
