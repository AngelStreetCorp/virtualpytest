# BUG-0305 — Canvas repeated the scope note in every panel

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0305                                                     |
| Reported  | 2026-10-04 (TASK-43 real-browser test)                       |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low — cosmetic / usability                                   |
| Area      | `frontend/src/components/agent-chat/AnalyticsArtifactViewer.tsx`, `analyticsExport.ts` |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

A canvas with several panels printed "Limited to the N host(s) of the selected server" once per panel (seen in a real-browser test on the production build).

## Root cause

`Panel` rendered `artifactDisclosures(spec)` for each panel and every panel of one question carries the same `options.scope_note`.

## Fix

A canvas shows each distinct scope note once above the panel grid; panels no longer print it (`artifactDisclosures(spec, includeScope)`). The HTML report does the same: distinct notes once at the top, panels without. A single visualization is unchanged.

## Verification

- `tsc --noEmit` passes.
- `tests/frontend/AnalyticsArtifactViewer.test.tsx` (once per canvas, each distinct note once, report carries it once).
