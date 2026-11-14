---
feature: F-10
title: Retrieval evaluation
status: planned
---

# Stories · F-10 Retrieval evaluation

Feature: [F-10](../features/F10-retrieval-evaluation.md)

## US-10.1 · Know whether retrieval works

As a Developer, I want a measured hit rate for tissue search and report search on held-out cases so that I can state how often the system finds relevant precedent, compared with chance.

- **Priority:** P1
- **Covers:** F-10.1, F-10.2, F-10.3, F-10.4, F-10.6
- **Acceptance:**
  - Given the demo cohort, when I run the evaluation, then I get precision at 5 and hit rate at 5 and at 10 for each search type, beside a random baseline.
  - Given the evaluation, when I check how it reads held-out reports, then it reads them from the database and not through the API.

## US-10.2 · Choose demo cases that hold up

As a Developer, I want the held-out cases ranked by how well retrieval performed on them so that the live demo uses cases where the result is real and repeatable.

- **Priority:** P1
- **Covers:** F-10.5
- **Acceptance:**
  - Given an evaluation run, when I open its output, then cases are listed best first with their retrieved cases, in markdown and JSON.
