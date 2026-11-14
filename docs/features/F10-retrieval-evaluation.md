---
id: F-10
title: Retrieval evaluation
status: planned
priority: P1
stories: [US-10.1, US-10.2]
models: [case, slide, report, patch]
screens: []
depends_on: [F-05, F-09]
linear: [SKO-282]
---

# F-10 · Retrieval evaluation

## Summary
A script measures whether search returns relevant cases, using the held-out cases whose real reports are hidden from search. It produces one number per search type and a list of cases where retrieval works well, used to choose the demo cases.

## Why
G3. Confidence in precedent depends on retrieval being right more often than chance. It also gives the presentation a measured result instead of a hand-picked one.

## Scope
**In**
- Offline evaluation over held-out cases.
- A report with metrics and per-case results.

**Out**
- Evaluating the agent's written answers.
- Any use of held-out reports at query time.

## Behaviour
1. For each held-out case, run slide-similarity search (Q3) from its slide, and report search (Q5) from its clinical history, each for the top 5 and top 10 cases.
2. A retrieved case is relevant if its ICD-10 code shares the first three characters with the held-out case's withheld code. A second, looser measure counts a match on specialty.
3. Report, per search type: mean precision at 5, hit rate at 5 (at least one relevant case), and the same at 10.
4. Report a random baseline computed from the corpus label distribution.
5. Write the result as markdown and JSON under `data/eval/`, including per-case scores sorted best first.
6. The script reads withheld reports directly from the database for scoring. It does not go through the API.

## API
None. Command-line only.

## Acceptance
- The script runs against the demo cohort and writes both files.
- Reported hit rate at 5 for slide similarity is above the random baseline, or the result is recorded as a finding in [architecture.md](../architecture.md#risks).
- The best-scoring cases are named so the demo script can use them.

## Open questions
None.
