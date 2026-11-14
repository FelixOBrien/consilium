---
feature: F-04
title: Report viewer
status: planned
---

# Stories · F-04 Report viewer

Feature: [F-04](../features/F04-report-viewer.md)

## US-04.1 · Read the report beside the slide

As a Pathologist, I want to read a case's report next to the slide, with extracted sections where headings exist and the full OCR text preserved, so that I can relate what was written to what I see.

- **Priority:** P0
- **Covers:** F-04.1, F-04.2
- **Acceptance:**
  - Given a signed-out case, when I open its report, then I see its non-empty extracted sections in order (clinical history, gross description, microscopic description, conclusion, additional information, ICD-10) and can read the full report body, with no text lost when headings are absent.
  - Given the report, when I read its header, then I see the author and sign-out date, marked synthetic.

## US-04.2 · See what is known about an unreported case

As a Pathologist, I want to see the clinical history of a case that has not been reported so that I know why the specimen was taken before I look at the slide.

- **Priority:** P0
- **Covers:** F-04.3
- **Acceptance:**
  - Given an open case, when I open its report, then I see the clinical history (when available) and a notice that the case is not yet reported.
  - Given an open held-out case, when I inspect what the server sent, then it contains no full report body, conclusion or microscopic description.

## US-04.3 · Use report wording on the slide and in case peek

As a Pathologist, I want to map informative report words onto the open slide and inspect other cases' reports in place so that I can connect report language to tissue without losing my place.

- **Priority:** P1
- **Covers:** F-04.4, F-04.5, F-04.6
- **Acceptance:**
  - Given an informative non-stop word in the report, when I select it, then a word-to-patch similarity overlay for that word appears on the open slide.
  - Given I am peeking at another case's report, when I read it, then it names its case and offers to open it.
