---
feature: F-12
title: Patient longitudinal history
status: planned
---

# Stories · F-12 Patient longitudinal history

Feature: [F-12](../features/F12-patient-history.md)

## US-12.1 · Review a patient's longitudinal case timeline

As a Pathologist, I want to open a patient's page from any of their cases and see every prior and current case in chronological order so that I know their diagnostic history before reporting a new specimen.

- **Priority:** P1
- **Covers:** F-12.1, F-12.2, F-12.3, F-12.5, F-12.7
- **Acceptance:**
  - Given a case whose patient has prior cases, when I read the case header or worklist row, then I see the patient label and prior-case indicator, and selecting the patient opens S-09.
  - Given S-09 for a multi-case patient, when I read the timeline, then cases appear newest first with specimen label, specialty, reporting pathologist, slide thumbnails and signed-out conclusions, while any open held-out case hides its withheld report and diagnosis codes.
  - Given a patient whose longitudinal link is synthetic, when I view S-09, then the synthetic-linkage disclosure is visible.

## US-12.2 · Search within one patient's prior cases

As a Pathologist, I want to search across a single patient's prior reports and slides so that I can quickly locate a specific finding or tissue pattern in a patient with multiple specimens.

- **Priority:** P1
- **Covers:** F-12.4, F-12.6
- **Acceptance:**
  - Given S-09 or a search filtered by `patient_id`, when I run a report or tissue query, then every returned hit belongs to a signed-out case of that patient.
  - Given corpus-wide evidence search on an open case whose patient has a matching signed-out prior case, when hits are shown, then the patient's own prior case is marked `same_patient`.

## US-12.3 · Ask the consult agent to summarise a patient's previous cases

As a Pathologist, I want the consult agent to retrieve and summarise the open patient's previous cases and reporting pathologists so that I have longitudinal context and know whether a colleague has already reported this patient.

- **Priority:** P1
- **Covers:** F-12.5, F-07.2, F-07.3, F-07.6
- **Acceptance:**
  - Given an open case belonging to a patient with signed-out prior cases, when I ask "Summarise this patient's previous cases", then the agent calls the patient history tool, summarises the prior signed-out findings in chronological order with `[case:<id>]` citations, and names who reported them.
  - Given a patient with an open case, when the agent retrieves patient history, then no withheld text or diagnosis code from any open case is returned to the model or shown.
