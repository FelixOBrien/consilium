# User Stories

This folder documents the user stories of the application. They are generated from the [features](../features/index.md): each feature has one stories file with the same file name, and every story says who needs part of that feature and how we know it works.

## Roles

| Role | Who they are | What they care about |
| --- | --- | --- |
| **Pathologist** | A doctor reporting a case. The primary user. In the app, the acting pathologist chosen from the roster. | Reaching a confident diagnosis quickly; knowing who to ask. |
| **Data operator** | The person who loads slides and reports into the system. | Ingestion that finishes, can be re-run, and reports what it did. |
| **Developer** | The team building and demonstrating the system. | Evidence that retrieval works; choosing reliable demo cases. |

Use these role names exactly. Add a role here before using a new one.

## Register

| File | Feature | Stories |
| --- | --- | --- |
| [F01-case-worklist.md](F01-case-worklist.md) | F-01 Case worklist | US-01.1 – US-01.3 |
| [F02-case-search.md](F02-case-search.md) | F-02 Case search | US-02.1 – US-02.3 |
| [F03-slide-viewer.md](F03-slide-viewer.md) | F-03 Slide viewer | US-03.1 – US-03.5 |
| [F04-report-viewer.md](F04-report-viewer.md) | F-04 Report viewer | US-04.1 – US-04.3 |
| [F05-evidence-search.md](F05-evidence-search.md) | F-05 Evidence search | US-05.1 – US-05.5 |
| [F06-phrase-heatmaps.md](F06-phrase-heatmaps.md) | F-06 Report-context similarity overlay | US-06.1 – US-06.3 |
| [F07-consult-agent.md](F07-consult-agent.md) | F-07 Consult agent | US-07.1 – US-07.4 |
| [F08-annotations.md](F08-annotations.md) | F-08 Annotations | US-08.1 – US-08.3 |
| [F09-ingestion.md](F09-ingestion.md) | F-09 Ingestion | US-09.1 – US-09.4 |
| [F10-retrieval-evaluation.md](F10-retrieval-evaluation.md) | F-10 Retrieval evaluation | US-10.1 – US-10.2 |
| [F12-patient-history.md](F12-patient-history.md) | F-12 Patient longitudinal history | US-12.1 – US-12.3 |

## Template

File name: the feature's file name. Copy this exactly.

```markdown
---
feature: F-NN
title: Feature title
status: planned            # planned | in-progress | done | cut
---

# Stories · F-NN Feature title

Feature: [F-NN](../features/FNN-kebab-title.md)

## US-NN.1 · Short name

As a <Role>, I want to <Goal> so that <Reason>.

- **Priority:** P0
- **Covers:** F-NN.1, F-NN.2
- **Acceptance:**
  - Given <starting state>, when <action>, then <observable result>.
```

## Rules for stories

- The sentence follows the form **As a \<Role\>, I want to \<Goal\> so that \<Reason\>.** One role, one goal, one reason.
- The goal is something the user does or sees, not an implementation step. "See similar tissue from other cases", not "query the vector index".
- The reason ties to an outcome in [vision.md](../vision.md), not a restatement of the goal.
- Every story has at least one acceptance line in Given / When / Then form that a person or a test can check.
- **Covers** lists the feature behaviour rules the story exercises. Every P0 rule of a feature is covered by at least one story.
- A story's priority is never higher than its feature's.
- Story IDs are permanent. A dropped story is marked `cut`, not renumbered.
