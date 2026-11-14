---
feature: F-04
title: Report viewer
status: planned
---

# Stories · F-04 Report viewer

Feature: [F-04](../features/F04-report-viewer.md)

## US-04.1 · Read the report beside the slide

As a Pathologist, I want to read a case's report in its standard sections next to the slide so that I can relate what was written to what I see.

- **Priority:** P0
- **Covers:** F-04.1, F-04.2
- **Acceptance:**
  - Given a signed-out case, when I open its report, then I see the non-empty sections in order: clinical history, gross description, microscopic description, conclusion, differential, additional information, ICD-10.
  - Given the report, when I read its header, then I see the author and sign-out date, marked synthetic.

## US-04.2 · See what is known about an unreported case

As a Pathologist, I want to see the clinical history of a case that has not been reported so that I know why the specimen was taken before I look at the slide.

- **Priority:** P0
- **Covers:** F-04.3
- **Acceptance:**
  - Given an open case, when I open its report, then I see the clinical history and a notice that the case is not yet reported.
  - Given an open held-out case, when I inspect what the server sent, then it contains no conclusion or microscopic description.

## US-04.3 · Use report wording as a query

As a Pathologist, I want to select a phrase in a report and search with it so that I can see where it appears on the slide or find other cases described the same way.

- **Priority:** P1
- **Covers:** F-04.4, F-04.5, F-04.6
- **Acceptance:**
  - Given selected text in a report, when I choose Show on slide, then a heatmap for that phrase appears on the open slide.
  - Given selected text, when I choose Find cases like this, then report search results for that text appear.
  - Given I am peeking at another case's report, when I read it, then it names its case and offers to open it.
