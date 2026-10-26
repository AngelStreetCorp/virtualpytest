# BUG-0316 — Analytics charts showed raw millisecond values that overflowed the Y axis

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0316                                                     |
| Reported  | 2026-10-04 (real browser, build 9786)                        |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low - cosmetic, labels unreadable                                                        |
| Area      | `frontend/src/components/agent-chat/AnalyticsArtifactViewer.tsx`                                                       |
| Fixed in  | build 90145 |
| Commit    | `3fd687987a`                                                     |

---

## Symptom

A "Duration Trend" line chart with `avg_duration_ms` up to ~1.6M showed Y ticks such as "1,800000 ms", clipped on the left of a canvas cell.

## Root cause

Ticks were `value + unit` with the raw number and the YAxis kept recharts' default 60 px width, so long labels were clipped.

## Fix

New display-only `formatDuration` / `formatAnalyticsValueWithUnit`: ms/s/min values show as ms, s, min or h (e.g. "30 min", "1.5 h") on axes, tooltips and table cells. The YAxis width is sized from the widest label. CSV/JSON/report exports keep raw numbers.

## Verification

Vitest `tests/frontend/AnalyticsArtifactViewer.test.tsx`; `tsc --noEmit` clean. Not checked in a real browser.
