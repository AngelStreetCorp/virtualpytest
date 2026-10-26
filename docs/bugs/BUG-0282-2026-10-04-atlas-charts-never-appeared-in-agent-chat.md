# BUG-0282 — Charts and tables Atlas rendered never appeared in Agent Chat

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0282                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — every Atlas chart, table and canvas was invisible     |
| Area      | `frontend/src/components/agent-chat/ContentViewer.tsx`, `AnalyticsArtifactViewer.tsx`, `frontend/src/pages/AgentChat.tsx` |
| Fixed in  | build 90145 |
| Commit    | `9d2d590bc`, `1cfacae11`                                     |

---

## Symptom

In `/ai-agent`, asking Atlas "compare pass rate by device" produced a successful
`render_analytics_artifact` call and a text table in the chat, but the side panel stayed on the
**Device** tab; no chart, comparison table or export bar was ever shown. Found by a Playwright run
of the real UI on both backend servers.

## Root cause

Agent Chat always passes the selected devices to `ContentViewer`, so the panel is always in
**tab mode**. Tab mode only renders its own tabs (Device, Userinterface, TestCase, Campaign,
Heatmap, Alerts) and never reaches the `report-chart` / `data-table` content. The analytics tests
covered `AnalyticsArtifactViewer` alone, and the API smoke test only checked tool results, so the
integration was never exercised. Table artifacts also went to a placeholder without the export
bar.

Seen in the same browser run: the comparison table was squeezed to one visible row above the
radar, recharts dropped overlapping category labels, API timestamps showed as raw ISO with
microseconds, 18 one-sided rows buried 5 regressions, and a result limited to the selected
server's hosts came back empty with nothing saying why.

## Fix

- A tab named after the artifact appears and is selected when Atlas returns a chart/table; the
  artifact is kept across tab switches and cleared on a new conversation. Table artifacts use the
  analytics viewer (export bar; SVG/PNG disabled for tables).
- Dates read `YYYY-MM-DD` / `YYYY-MM-DD HH:MM`; an empty result says "No data matched this
  question"; the comparison table keeps its height and folds rows with one side missing behind a
  toggle; dense bar charts show every label, angled; a `scope_note` says when the result is
  limited to the selected server's hosts (also given to the model, with "do not substitute other
  devices").

## Verification

- `tests/frontend/ContentViewerAnalytics.test.tsx` (tab mode shows the artifact with its export bar,
  no tab before an artifact, empty state, timestamp format, comparison fold and scope note) and the
  updated `AnalyticsArtifactViewer` tests.
- Playwright on the production bundle 9709, both servers, four prompts each: the tab appears and is
  selected, charts/tables render, the export bar works and CSV downloads have header and rows,
  tab switching keeps the artifact, New Chat removes it, no raw ISO timestamps.
