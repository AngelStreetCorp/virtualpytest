# BUG-0317 — Analytics table panel was cut off inside a canvas cell

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0317                                                     |
| Reported  | 2026-10-04 (real browser, build 9786)                        |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low - cosmetic, data hidden                                                        |
| Area      | `frontend/src/components/agent-chat/AnalyticsArtifactViewer.tsx`                                                       |
| Fixed in  | Unreleased                                                   |
| Commit    | `3fd687987a`                                                     |

---

## Symptom

A "Failing Test Cases" table in a 3-column canvas cell lost its right columns; the header read "fa c" for failure_count and nothing could scroll.

## Root cause

Headers wrapped mid-word because the table was squeezed to the cell width, and the card had no min-width so the content was clipped.

## Fix

Table headers stay on one line (`nowrap`, snake_case shown with spaces), the table has `min-width: max-content` inside an `overflow: auto` wrapper so it scrolls horizontally, and the canvas card has `min-width: 0`.

## Verification

Vitest `tests/frontend/AnalyticsArtifactViewer.test.tsx`; `tsc --noEmit` clean. Not checked in a real browser.
