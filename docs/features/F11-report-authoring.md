---
id: F-11
title: Report authoring and sharing
status: cut
priority: P2
stories: []
models: [report]
screens: []
depends_on: [F-04]
linear: []
---

# F-11 · Report authoring and sharing

## Summary
A pathologist writes the report for an open case, signs it out, and shares the case with a colleague for an opinion.

Cut for the hackathon. The vision includes it, but the time before the freeze goes to retrieval and the consult agent, which are what the track and the Databricks bounty reward. The data model already allows for it: `report.status` has a `draft` value and `report.author_id` exists.

## Why
G2, in the longer-term product.

## Scope
**In** — None for the hackathon.

**Out** — Everything: editing, sign-out, sharing, notifications.

## Behaviour
None.

## API
None.

## Acceptance
None.

## Open questions
- If time appears: the smallest useful version is a free-text conclusion saved as a draft on an open case.
