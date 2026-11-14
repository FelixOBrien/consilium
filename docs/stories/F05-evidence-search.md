---
feature: F-05
title: Evidence search
status: planned
---

# Stories · F-05 Evidence search

Feature: [F-05](../features/F05-evidence-search.md)

## US-05.1 · Find tissue that looks like this

As a Pathologist, I want to select tissue on the open slide and see similar tissue from other cases so that I can check my impression against cases that have already been signed out.

- **Priority:** P0
- **Covers:** F-05.1, F-05.2, F-05.6, F-05.8, F-05.13, F-05.14
- **Acceptance:**
  - Given a selected patch, when I choose Find similar tissue, then within 2 seconds I see up to 20 other cases, each with patch thumbnails, specialty, ICD-10, conclusion line and author.
  - Given the results, when I look for the open case or any open case, then neither appears.
  - Given a drawn region instead of a single patch, when I search, then results reflect the whole region.

## US-05.2 · Find cases like this slide

As a Pathologist, I want to ask for cases similar to the whole slide so that I get a starting set of precedent without choosing a region first.

- **Priority:** P0
- **Covers:** F-05.4, F-05.6
- **Acceptance:**
  - Given an open slide, when I choose Cases like this slide, then I see cases ranked by similarity, each with its three most similar patches.

## US-05.3 · Describe tissue in words

As a Pathologist, I want to type a description of a tissue pattern and see matching regions in other cases so that I can find examples of a feature I can name but have not located.

- **Priority:** P0
- **Covers:** F-05.2, F-05.7, F-05.13
- **Acceptance:**
  - Given a morphology description, when I search, then within 3 seconds I see cases with matching patches.
  - Given the same description with a specialty filter, when I search, then every result is of that specialty.

## US-05.4 · Search reports from inside a case

As a Pathologist, I want to search report text without leaving the case so that I can pull up how colleagues reported a finding while I keep the slide in view.

- **Priority:** P0
- **Covers:** F-05.5, F-05.6
- **Acceptance:**
  - Given a text query in Reports mode, when I search, then I see cases with the best-matching passage, and the open case is not among them.

## US-05.5 · Go from a result to its evidence

As a Pathologist, I want to open a result at the matching region and read its report so that I can judge for myself whether it is relevant.

- **Priority:** P0
- **Covers:** F-05.10, F-05.11, F-05.12
- **Acceptance:**
  - Given a result, when I peek at it, then I see the patch larger and the case's report without leaving the open case.
  - Given a result, when I open it, then that case's workspace opens with the viewer centred on the patch.
  - Given results on screen, when I send them to the consult agent, then my next question is answered using those cases.
  - Given a search scoped to this slide, when results return, then matching regions are marked on the open slide.
