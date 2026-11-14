---
feature: F-01
title: Case worklist
status: planned
---

# Stories · F-01 Case worklist

Feature: [F-01](../features/F01-case-worklist.md)

## US-01.1 · See my open cases

As a Pathologist, I want to see the open cases assigned to me so that I can start on the next case without searching for it.

- **Priority:** P0
- **Covers:** F-01.1, F-01.2, F-01.3, F-01.4, F-01.6
- **Acceptance:**
  - Given I am acting as a pathologist with open cases, when I open the app, then I see those cases newest first, each with specialty, patient age and sex, slide thumbnail and status.
  - Given an open case in the list, when I read its row, then it shows no report conclusion.
  - Given the list, when I select a case, then its workspace opens.

## US-01.2 · Browse and filter all cases

As a Pathologist, I want to browse every case and filter by specialty, status, pathologist and ICD-10 code so that I can find a group of cases, such as everything a colleague has reported.

- **Priority:** P0
- **Covers:** F-01.4, F-01.5
- **Acceptance:**
  - Given All cases, when I filter by specialty and status, then only matching cases are listed and the URL contains the filters.
  - Given a filtered URL, when I reload it, then the same filtered list appears.
  - Given more than 50 matching cases, when I reach the end of the list, then the next page loads.

## US-01.3 · Choose who I am

As a Pathologist, I want to choose which pathologist I am acting as so that the worklist, annotations and consult threads are mine.

- **Priority:** P0
- **Covers:** F-01.7, F-01.8
- **Acceptance:**
  - Given the roster, when I choose a pathologist, then My cases shows that pathologist's cases and the choice survives a reload.
  - Given the roster is shown, when I read it, then it is marked as synthetic.
