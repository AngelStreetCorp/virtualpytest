# BUG-0314 — Analytics bar chart labels ran over the legend in canvas cells

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0314                                                     |
| Reported  | 2026-10-04 (real browser, build 9777)                        |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low - cosmetic, legend unreadable                                                        |
| Area      | `frontend/src/components/agent-chat/AnalyticsArtifactViewer.tsx`                                                       |
| Fixed in  | build 90145 |
| Commit    | `c92efe050e`                                                     |

---

## Symptom

A bar chart with more than 6 long category labels (KPI averages by `acceptance-stb4-tv-20261002-0607-stb`) angled its x labels, which in a canvas cell ran over the legend text (`avg_kpi_ms`).

## Root cause

The angled labels were longer than the 70 px XAxis height (the margin hack did not add room), so they spilled into the legend below.

## Fix

Dense bar charts reserve an 80 px XAxis height and truncate tick labels to 18 characters with an ellipsis (`truncateTick`). The tooltip, table and exports keep the full value.

## Verification

Vitest `tests/frontend/AnalyticsArtifactViewer.test.tsx` (`truncateTick`, reserved axis height; jsdom draws no tick text); `tsc --noEmit` clean. Not checked in a real browser.
