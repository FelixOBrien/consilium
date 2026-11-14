# Screens

This folder documents where the features appear and what each screen does. Screens are generated from the [features](../features/index.md) and [stories](../stories/index.md). These docs describe **function**: what is on a screen, what data it shows, what each action does, and how it behaves when loading, empty or failing. Visual design is done in Figma and is not described here.

## Register

| ID | Screen | Route | Priority | Features |
| --- | --- | --- | --- | --- |
| [S-01](S01-worklist.md) | Worklist | `/` | P0 | F-01, F-02 |
| [S-02](S02-case-workspace.md) | Case workspace and viewer | `/cases/[caseId]` | P0 | F-03, F-06 |
| [S-03](S03-report-panel.md) | Report panel | in S-02, `panel=report` | P0 | F-04 |
| [S-04](S04-evidence-panel.md) | Evidence panel | in S-02, `panel=evidence` | P0 | F-05 |
| [S-05](S05-consult-panel.md) | Consult panel | in S-02, `panel=consult` | P0 | F-07 |
| [S-06](S06-annotations-panel.md) | Annotations panel | in S-02, `panel=annotations` | P1 | F-08 |
| [S-07](S07-search.md) | Search | `/search` | P0 | F-02 |
| [S-08](S08-ingestion.md) | Ingestion | `/ingest` | P2 | F-09 |
| [S-09](S09-patient.md) | Patient | `/patients/[patientId]` (plus `/patients` directory) | P1 | F-12, F-02, F-05 |

## Navigation

```
                 ┌──────── global bar: Worklist · Patients · search box · acting pathologist · Ingest ────────┐
                 │                                                                                            │
   S-01 Worklist ──select case──► S-02 Case workspace ◄──open result── S-07 Search ◄────────── search box ────┤
        │                          │  │  viewer + one side panel at a time                                    │
        └──select patient──┐       │  ├─ S-03 Report                                                          │
                           ▼       │  ├─ S-04 Evidence ──open result──► S-02 of another case, at a location   │
                     S-09 Patient ◄┘  ├─ S-05 Consult  ──open citation─► S-02 of another case                 │
                       │              └─ S-06 Annotations                                                     │
                       └─open case──► S-02 Case workspace                                                     │
   S-08 Ingestion ──job done──► S-02 of the new case ◄────────────────────────────────────────────────────────┘
```

## Shared elements

Present on every screen and specified once here.

| Element | Function |
| --- | --- |
| Global search box | Submitting opens [S-07](S07-search.md) with the query (F-02.1). |
| Acting pathologist | Shows who the user is acting as; opens the roster to change it (F-01.7). Marked synthetic. |
| Research notice | A persistent statement that this is a research prototype and not for clinical use. |
| Case peek | An overlay showing another case's summary, a patch at larger size if one is given, and its report (F-04.5), with an action to open that case. Used by S-04, S-05 and S-07. |

## URL state

State that should survive reload or be shareable lives in the URL, not only in memory.

| Parameter | On | Meaning |
| --- | --- | --- |
| `view`, `status`, `specialty`, `assigned_to`, `icd10`, `patient_id` | S-01 | Worklist view and filters. |
| `slide`, `x`, `y`, `zoom` | S-02 | Slide and viewport, level-0 pixels (F-03.5). |
| `panel` | S-02 | Which side panel is open: `report`, `evidence`, `consult`, `annotations`. |
| `q`, `mode`, filters (including `patient_id`) | S-07 | Query, `reports` or `tissue`, and filters. |
| `q`, `mode` | S-09 | Optional patient-scoped search query and mode (`reports` or `tissue`). |

## Template

File name: `SNN-kebab-title.md`. Copy this exactly.

```markdown
---
id: S-NN
title: Title
route: /path/[param]       # or "panel in S-NN"
status: planned            # planned | in-progress | done | cut
priority: P0
features: [F-NN]
stories: [US-NN.n]
figma: ""                  # frame link, added when designed
linear: []
---

# S-NN · Title

## Purpose
One or two sentences: what the user comes here to do.

## Entry points
How the user arrives, and with what state.

## Regions
A table of the functional areas of the screen: what each contains.

## Data
Which API route feeds each region.

## Actions
A table: user action → what happens → API call.

## States
Loading, empty, error, and any other state that changes what is shown.

## Out of scope
What this screen does not do.
```

## Rules for screen docs

- Describe regions by what they contain and do, never by position, size, colour or component library.
- Every action names the feature rule it implements and the API route it calls.
- Every region that loads data has loading, empty and error states.
- A screen invents no behaviour. If an action has no feature rule behind it, add the rule to the feature first.
- When a Figma frame exists, link it in the front matter; the frame is the source for appearance and this doc stays the source for behaviour.
