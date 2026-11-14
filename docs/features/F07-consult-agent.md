---
id: F-07
title: Consult agent
status: planned
priority: P0
stories: [US-07.1, US-07.2, US-07.3, US-07.4]
models: [consult_thread, consult_message, case, report, pathologist, search_hit]
screens: [S-05]
depends_on: [F-05]
linear: [SKO-271, SKO-279, SKO-285]
---

# F-07 · Consult agent

## Summary
While viewing a case, a pathologist asks questions in plain language, such as "who would be best to consult on this case?". An agent searches for similar cases by tissue and by report text, reads the reports, and answers with a brief that cites the cases it used and ranks the pathologists who reported them.

## Why
G2. The first consult request goes to the colleague with the most relevant experience, with the evidence attached, instead of being found by asking around. This is also the multi-step agent the Autonomous Agents track judges.

## Scope
**In**
- A conversation attached to a case.
- Retrieval over reports and patches through tools.
- Cited answers and a pathologist ranking.

**Out**
- Stating or suggesting a diagnosis for the open case.
- Sending a consult request to anyone.
- Web search or knowledge outside the indexed cases.

## Tools

| Tool | Input | Returns |
| --- | --- | --- |
| `get_case_context` | — | The open case: specialty, age, sex, clinical history, slides, and the report if signed out. |
| `search_similar_cases_by_morphology` | optional `slide_id`, `region`, `filters` | Cases ranked by tissue similarity to the open slide or region ([F-05](F05-evidence-search.md) Q2, Q3). |
| `search_patches_by_text` | `text`, `filters` | Cases whose patches match a morphology description (Q4). |
| `search_reports` | `text`, `filters` | Cases whose reports match (Q5), with passages. |
| `get_report` | `case_id` | One full signed-out report with author. |
| `rank_pathologists` | `case_ids` | For those cases: each author, number of the cases they reported, their specialty, and the case IDs. Computed in SQL. |

## Behaviour
1. A thread belongs to one case and one acting pathologist. Opening the consult panel resumes the most recent thread for that pair or starts one.
2. Three starter questions are offered: who to consult on this case, summarise similar cases, and what features distinguished similar cases.
3. For a who-to-consult question the agent gathers evidence from tissue similarity and from report text before answering, then calls `rank_pathologists` on the cases it judged relevant.
4. A consult answer contains: a ranked list of pathologists with the count of relevant cases each reported and their specialty; the cases behind each count; and one or two sentences on why those cases are relevant.
5. Every count comes from a `rank_pathologists` result. The agent does not count for itself.
6. Every statement about a prior case cites its case ID. Citations in the answer are structured, so the UI can open or peek at the case.
7. The agent does not state a diagnosis for the open case. Asked for one, it says it cannot, and offers what similar signed-out cases concluded, attributed to those cases.
8. Tools never return open cases, withheld reports or the open case's own report as precedent.
9. If the pathologist has a region selected or evidence results on screen, they can be attached to the question; the agent then starts from those instead of searching from scratch.
10. The answer streams. Each tool call is shown as a step while it runs, with a one-line result such as the number of cases found.
11. A turn makes at most 8 tool calls. Tool results are trimmed to the fields the agent needs, with report passages rather than full reports unless `get_report` is called.
12. If retrieval finds nothing relevant, the agent says so rather than naming someone.
13. Threads and messages are stored, including citations and the tool trace.
14. Pathologist names shown in answers are marked synthetic in the UI.
15. The pathologist can stop an answer while it streams; the partial answer is kept. They can also start a new thread for the case, which replaces the one shown.

## API
- `POST /api/cases/{id}/consult/threads` — start or resume the thread for the acting pathologist. Body `new: true` forces a fresh thread.
- `GET /api/consult/threads/{id}` — the thread with its messages.
- `POST /api/consult/threads/{id}/messages` — body: `content`, optional `attachments` (`region`, `case_ids`). Responds as a server-sent event stream: `step`, `text`, `citations`, `ranking`, `done`, `error`.

## Acceptance
- On a demo case, "who should I consult?" produces at least two tool steps, a ranked list with counts, and citations that open the cited cases.
- Each count in the answer equals the number of cited cases for that pathologist.
- Asked "what is the diagnosis?", the agent declines and offers precedent.
- The stream shows steps as they happen, and reloading the page restores the thread.

## Open questions
- Whether the App can reach the Anthropic API from Databricks Free Edition. See [architecture.md](../architecture.md#risks).
