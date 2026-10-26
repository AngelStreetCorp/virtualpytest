# BUG-0345 — Atlas thrashed for 46 s on an empty KPI comparison instead of answering "no data"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0345                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | Low - slow and noisy answer, correct conclusion              |
| Area      | `backend_server/src/lib/analytics/service.py`, `backend_server/src/mcp/tools/analytics_tools.py` |
| Fixed in  | build 90145 |

---

## Symptom

"compare Base and variant1 KPI for stb_tv over the last 30 days and show only regressions over 10%" on the main server
(its hosts hold no stb_tv KPI samples; they live on the Pi server). `query_kpi_radar` correctly returned 0 rows, then the
model made 12 `query_analytics_data` calls, a describe, 3 renders and 4 errors (guessed fields) before answering "no data".

## Root cause

The empty-result reply said only "NO DATA matched", so the model could not tell "nothing exists here" from "I asked wrong".

## Fix

An empty `kpi_measurements` result now runs one small availability query on the same path (team, scope, server narrowing,
Pi forwarding) and the tool reply says what exists in scope (interfaces with sample counts, capped at 8, or the variants
that do exist for the requested interface, or "none at all"). Every empty reply, any source, ends with "Answer now; do not
run more queries for this question." Non-empty results run no extra query.
Tests: `tests/backend_server/test_atlas_analytics.py` (`test_empty_kpi_result_*`, `test_non_empty_kpi_result_runs_no_availability_query`, `test_empty_non_kpi_result_still_says_answer_now`).
