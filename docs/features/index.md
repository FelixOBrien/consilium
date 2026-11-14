# Features

This folder documents what the application does. A feature is one capability a user would name. Features come from [vision.md](../vision.md); stories, models and screens are derived from features.

## Register

| ID | Feature | Priority | Status | Stories | Screens |
| --- | --- | --- | --- | --- | --- |
| [F-01](F01-case-worklist.md) | Case worklist | P0 | planned | [US-01](../stories/F01-case-worklist.md) | S-01 |
| [F-02](F02-case-search.md) | Case search | P0 | planned | [US-02](../stories/F02-case-search.md) | S-01, S-07 |
| [F-03](F03-slide-viewer.md) | Slide viewer | P0 | in-progress | [US-03](../stories/F03-slide-viewer.md) | S-02 |
| [F-04](F04-report-viewer.md) | Report viewer | P0 | planned | [US-04](../stories/F04-report-viewer.md) | S-03 |
| [F-05](F05-evidence-search.md) | Evidence search | P0 | planned | [US-05](../stories/F05-evidence-search.md) | S-04 |
| [F-06](F06-phrase-heatmaps.md) | Report-context similarity overlay | P1 | planned | [US-06](../stories/F06-phrase-heatmaps.md) | S-02, S-03 |
| [F-07](F07-consult-agent.md) | Consult agent | P0 | planned | [US-07](../stories/F07-consult-agent.md) | S-05 |
| [F-08](F08-annotations.md) | Annotations | P1 | planned | [US-08](../stories/F08-annotations.md) | S-06 |
| [F-09](F09-ingestion.md) | Ingestion | P0 bulk, P2 live | planned | [US-09](../stories/F09-ingestion.md) | S-08 |
| [F-10](F10-retrieval-evaluation.md) | Retrieval evaluation | P1 | planned | [US-10](../stories/F10-retrieval-evaluation.md) | — |
| [F-11](F11-report-authoring.md) | Report authoring and sharing | — | cut | — | — |
| [F-12](F12-patient-history.md) | Patient longitudinal history | P1 | planned | [US-12](../stories/F12-patient-history.md) | S-01, S-02, S-05, S-07, S-09 |

## Build order

P0 features form one path: F-09 produces the data, F-01 and F-03 make it visible, F-04 and F-05 make it useful, F-07 is the agent the track judges. F-02 reuses F-05's search. P1 features attach to the working viewer.

```
F-09 ──► F-01 ──► F-03 ──► F-04
                    ├────► F-05 ──► F-07 ──► F-12
                    │        └────► F-02
                    ├────► F-06
                    └────► F-08
F-09 + F-05 ──► F-10
```

## Template

File name: `FNN-kebab-title.md`. Copy this exactly.

```markdown
---
id: F-NN
title: Title in sentence case
status: planned            # planned | in-progress | done | cut
priority: P0               # P0 | P1 | P2
stories: [US-NN.1]
models: [table_name]
screens: [S-NN]
depends_on: [F-NN]
linear: []                 # issue IDs, added when issues exist
---

# F-NN · Title

## Summary
Two or three sentences: what the user can do.

## Why
Which goal in vision.md (G1, G2, G3) this serves and how.

## Scope
**In** — bullet list.
**Out** — bullet list of things a reader might assume are included.

## Behaviour
Numbered rules, each testable. Reference them elsewhere as F-NN.3.

## API
Routes this feature owns, with one line each.

## Acceptance
Checks that can be run in a demo or a test. Each maps to a story.

## Open questions
Bullets, or "None."
```

## Rules for feature docs

- Behaviour rules say what happens, not how it looks. Layout belongs to the screen doc and to Figma.
- A rule that needs data names the model field it reads.
- A feature owns its routes. Two features do not define the same route; the second links to the first.
- If a feature is cut, set `status: cut`, keep the file, and say why under Summary.
