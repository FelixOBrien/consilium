---
feature: F-02
title: Case search
status: planned
---

# Stories · F-02 Case search

Feature: [F-02](../features/F02-case-search.md)

## US-02.1 · Find a case by what its report says

As a Pathologist, I want to search cases by words from their reports so that I can find a case I remember by its diagnosis or wording.

- **Priority:** P0
- **Covers:** F-02.1, F-02.2, F-02.3, F-02.4, F-02.6, F-02.9
- **Acceptance:**
  - Given a signed-out case whose conclusion contains a distinctive term, when I search for that term, then the case is in the top three with the matching passage shown.
  - Given a case ID or an ICD-10 code as the query, when I search, then that case, or the cases with that code, are listed first.
  - Given results, when I apply a specialty filter, then only cases of that specialty remain.

## US-02.2 · Find cases by meaning, not exact words

As a Pathologist, I want search to match reports that mean the same thing in different words so that I do not miss precedent because a colleague phrased it differently.

- **Priority:** P0
- **Covers:** F-02.2, F-02.4, F-02.7
- **Acceptance:**
  - Given a signed-out report, when I search with a paraphrase that shares no keywords with it, then the case is in the top ten and is marked as matched by meaning.
  - Given any query, when results are shown, then none contains text from a held-out report.

## US-02.3 · Find cases by describing tissue

As a Pathologist, I want to describe what tissue looks like and get cases whose slides contain it so that I can find examples of a pattern even when no report mentions it.

- **Priority:** P1
- **Covers:** F-02.5, F-02.8
- **Acceptance:**
  - Given Tissue mode, when I enter a morphology description, then cases are listed with up to three matching patch thumbnails each.
  - Given a tissue result, when I open it, then the viewer is centred on that patch.
