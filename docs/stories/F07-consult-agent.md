---
feature: F-07
title: Consult agent
status: planned
---

# Stories · F-07 Consult agent

Feature: [F-07](../features/F07-consult-agent.md)

## US-07.1 · Find out who to consult

As a Pathologist, I want to ask who would be best to consult on this case so that my first request goes to the colleague with the most relevant experience.

- **Priority:** P0
- **Covers:** F-07.1, F-07.2, F-07.3, F-07.4, F-07.5, F-07.12, F-07.14
- **Acceptance:**
  - Given an open case, when I ask who to consult, then I get a ranked list of pathologists, each with the number of relevant cases they reported and their specialty.
  - Given the ranking, when I count the cited cases for a pathologist, then the count matches the number stated.
  - Given a case with no relevant precedent, when I ask, then I am told nothing relevant was found and nobody is named.

## US-07.2 · Check the evidence behind an answer

As a Pathologist, I want every claim about a prior case to link to that case so that I can verify the answer instead of trusting it.

- **Priority:** P0
- **Covers:** F-07.6, F-07.8, F-07.13
- **Acceptance:**
  - Given an answer, when I select a citation, then I can peek at or open the cited case.
  - Given any answer, when I check its citations, then none is an open case or the case I am viewing.
  - Given a thread, when I reload the page, then the conversation and its citations are restored.

## US-07.3 · Watch the agent work

As a Pathologist, I want to see what the agent is searching for as it works so that I understand how it reached its answer and can tell when it is still running.

- **Priority:** P0
- **Covers:** F-07.10, F-07.11
- **Acceptance:**
  - Given a question, when the agent runs, then each search appears as a step with a one-line result before the answer finishes.
  - Given a who-to-consult question, when the agent runs, then I see at least one tissue search and one report search.

## US-07.4 · Ask about a specific region or result set

As a Pathologist, I want to attach a region I selected, or the results I am looking at, to my question so that the answer is about the tissue I care about.

- **Priority:** P1
- **Covers:** F-07.7, F-07.9
- **Acceptance:**
  - Given a selected region, when I ask about it, then the agent's tissue search starts from that region.
  - Given I ask for the diagnosis of this case, when the agent answers, then it declines and offers what similar signed-out cases concluded, attributed to those cases.
