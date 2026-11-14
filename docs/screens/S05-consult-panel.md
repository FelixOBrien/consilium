---
id: S-05
title: Consult panel
route: panel in S-02 (panel=consult)
status: planned
priority: P0
features: [F-07]
stories: [US-07.1, US-07.2, US-07.3, US-07.4]
figma: ""
linear: [SKO-279]
---

# S-05 · Consult panel

## Purpose
The pathologist asks the agent about the open case, watches it search, and gets a cited answer, including who to consult.

## Entry points
- The Consult entry in the S-02 panel switch: resumes the latest thread for this case and acting pathologist, or starts one.
- Ask about this region, from a selection or annotation: opens with the region attached to the input.
- Send results to consult, from S-04: opens with those cases attached.

## Regions

| Region | Contains |
| --- | --- |
| Starter questions | Shown when the thread is empty: Who should I consult on this case? · Summarise similar cases · What features distinguished similar cases? |
| Conversation | Messages in order. User messages show any attachment. Assistant messages show steps, answer text with inline citations, and a ranking card when present. |
| Steps | Within an assistant message: one line per tool call, showing what was searched and a one-line result, updating live while running (F-07.10). Collapsible once the answer is complete. |
| Ranking card | Within an assistant message: pathologists in order, each with specialty, the number of relevant cases, and those cases as citations. Marked synthetic (F-07.4, F-07.14). |
| Citations | Inline case references in the answer, and the list of all cited cases under it. |
| Input | A text field, attachment chips (region thumbnail, or "N cases from evidence") that can be removed, and send. A stop control while an answer streams. |
| Notice | That the agent retrieves and summarises prior cases and does not diagnose. |

## Data

| Region | Route |
| --- | --- |
| Thread on open | `POST /api/cases/{id}/consult/threads` |
| Conversation | `GET /api/consult/threads/{id}` |
| A new answer | `POST /api/consult/threads/{id}/messages`, as an event stream |
| Citation peek | `GET /api/cases/{id}`, `GET /api/cases/{id}/report` |

Stream events map to regions: `step` → Steps, `text` → answer text, `citations` → Citations, `ranking` → Ranking card, `done` and `error` → message status.

## Actions

| Action | Result | API |
| --- | --- | --- |
| Select a starter question | Sends it as a message (F-07.2). | `POST …/messages` |
| Send a message | The user message appears; an assistant message starts streaming with its steps (F-07.10). | `POST …/messages` |
| Remove an attachment | The message will be sent without it (F-07.9). | — |
| Stop | The stream is closed; the partial answer is kept and marked stopped. | — |
| Select a citation | Opens the case peek for that case (F-07.6). | `GET /api/cases/{id}`, `/report` |
| Open from the peek | Navigates to S-02 for the cited case, at the cited patch if there is one. | — |
| Select a pathologist in the ranking | Opens S-01 filtered to their signed-out cases. | — |
| Expand or collapse steps | Shows or hides the tool trace of a completed answer. | — |
| Start a new thread | Creates a fresh thread for the case; the old one is no longer shown. | `POST /api/cases/{id}/consult/threads` with `new: true` |

## States
- **Empty thread** — starter questions and the notice.
- **Streaming** — steps appear as they run, then text; input is disabled except for stop.
- **No relevant precedent** — the agent's statement that nothing relevant was found; no ranking card (F-07.12).
- **Declined** — when asked for a diagnosis, the answer says it cannot give one and offers precedent (F-07.7). Shown as a normal answer.
- **Error** — the assistant message shows that the answer failed, with retry of the same question. Earlier messages are unaffected.
- **Agent unavailable** — if the model provider cannot be reached, the panel says so; the rest of the workspace keeps working.
- **Restored** — after reload, completed messages show with steps collapsed.

## Out of scope
- Sending a consult request or message to a pathologist.
- Editing or deleting individual messages.
- Showing a list of past threads.
- Voice input.
