# BUG-0306 — Radar chart rendered below the comparison table, out of sight

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0306                                                     |
| Reported  | 2026-10-04 (TASK-43 real-browser test)                       |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — cosmetic / usability                                   |
| Area      | `frontend/src/components/agent-chat/AnalyticsArtifactViewer.tsx` |
| Fixed in  | Unreleased                                                   |
| Commit    | this commit                                                  |

---

## Symptom

With a `comparison` block and a radar, the table (max-height 280) came first and the radar under it, so the chart needed a scroll to be seen.

## Root cause

`Panel` always rendered `ComparisonTable` before the chart.

## Fix

For a comparison with a chart mark the chart is first: side by side with the table when the panel is wide (flex-wrap, 420px basis), chart on top when narrow. The regression caption, the one-sided fold and the export bar are untouched.

## Verification

- `tsc --noEmit` passes.
- `tests/frontend/AnalyticsArtifactViewer.test.tsx` (chart precedes the table; fold and export bar present).
