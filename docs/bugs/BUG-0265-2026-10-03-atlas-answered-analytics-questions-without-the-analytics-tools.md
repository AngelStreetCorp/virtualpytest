# BUG-0265 — Atlas answered analytics questions without its analytics tools

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0265                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — most chart/statistics questions never reached the analytics layer |
| Area      | `backend_server/src/agent/core/manager.py` (router tool selection) |
| Fixed in  | Unreleased                                                   |
| Commit    | `26c9672f3`                                                       |

---

## Symptom

In Agent Chat, "show failing testcases for this device" made Atlas call `get_device_info` and
`list_testcases` and reply that testcase status is not available. "Show degraded hosts",
"show only regressions over 10%", "build a canvas with pass rate, duration trend and failing
cases" and "show platform service availability" got no analytics tool at all.

## Root cause

In router mode Atlas is offered only 12 tools per message, chosen by keyword score. The
analytics category hints were only `analytics, data, database, kpi, radar, graph, chart, metric`,
so questions phrased as "failing", "pass rate", "degraded", "regression", "trend" or "canvas"
scored the device, testcase and alert tools above the analytics ones. Measured offline on the ten
smoke prompts: 5 got no analytics tool, and 2 got only a shortcut or the Grafana-draft tool.

## Fix

The analytics hints cover the vocabulary of the presets (failing, pass rate, compare, regression,
trend, duration, canvas, degraded, fleet, occupancy, availability, incidents, export, Grafana, …),
and a message that matches them always gets the core analytics tools
(`list_analytics_sources`, `query_analytics_data`, `render_analytics_artifact`), reserved like
the docs tools, within the existing quota.

## Verification

- `tests/backend_server/test_agent_minimax_quirks.py::test_router_offers_analytics_core_tools_for_analytics_questions`
  (all 7 TASK-43 acceptance prompts; a navigation prompt does not get them).
- Live Atlas smoke test after deploy (TASK-43 `.deploy_blocker.md` prompts).
