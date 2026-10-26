# BUG-0730 — The Errors tab says "No errors in this period" while the same page reports 416 failed calls

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0730                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                        |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | `d5289bf` (deployed 2026-10-21, build 89471)                |

---

## Symptom

On `/monitoring/ai-usage` (period "24 h", team scope), the **Errors** tab renders a single line:

> No errors in this period.

The same page, on the Overview tab, shows **"416 failed calls · see Efficiency"**, and the Usage
tab's *Errors* column shows **324** failed calls. The provider panel on the Providers tab shows
**298** failed OpenRouter calls, 5 on MiniMax VLM and 5 on Anthropic.

Three numbers for one period, and the tab named "Errors" is the one that says there are none.

The header badge next to the page title ("N errors") also reads **0**, so the single
"something is wrong" signal on the page never fires.

The Efficiency tab repeats it: its *"Wasted requests, by cause and feature"* panel shows
*"No wasted requests in this period."* directly under a tile reading **416** wasted requests.

## Root cause

Three different quantities are called "error", and the one the Errors tab renders is a fourth.

1. `totals.errors` — calls whose `ok` is false. On the live server: **324**.
2. `overview.totals.wasted` — calls that produced no usable output: failed **or** empty **or**
   unreadable (not valid JSON) **or** cut off by the token limit. On the live server: **416**
   (`shared/src/lib/ai/usage_view.py:139-141`).
3. `report.errors` — **provider-health cause groups**, built by `_banner()`
   (`backend_server/src/routes/server_ai_routing_routes.py:515-524`) from `health.evaluate`.

The page assigns the third one to the Errors tab and sets:

```python
report['errors'] = {'count': len(causes), 'causes': causes}
# backend_server/src/routes/server_ai_routing_routes.py
```

so `errors.count` is the number of **cause groups**, and `ErrorsTab.tsx:34` renders
*"No errors in this period."* when that list is empty.

The list is empty because `health.evaluate` keeps a cause **only** when that
`(endpoint, usage_key)` pair is currently worse than a threshold:

```python
if not h or h["calls"] < limits["min_requests"] or h["errors"] / h["calls"] <= limits["error_rate"]:
    continue                      # shared/src/lib/ai/health.py:92
```

with `DEFAULT_MIN_REQUESTS = 20` and `DEFAULT_ERROR_RATE = 0.05`
(`shared/src/lib/ai/health.py:20-22`, overridable by `AI_ALERT_MIN_REQUESTS` /
`AI_ALERT_ERROR_RATE`). The 298 OpenRouter failures were spread over many usage keys, so no
single pair crossed the threshold.

Two further consequences:

- the cause list is evaluated over **the last 24 h** (`server_ai_routing_routes.py:653`, `:516`),
  **not** the selected period — the tab does not change when the period does;
- the header badge renders `report.errors.count` as "{n} errors"
  (`frontend/src/pages/MonitoringAiUsage.tsx:184`), i.e. it counts cause groups, not failures.

## Fix

**Fixed 2026-10-21 by the TASK-147 redesign** (overview → provider/feature → call): the Errors tab is gone. The overview's *Failing now* counts failed calls of the last two hours with the time of the last failure, and every provider and feature has a *Failed* switch that lists its failed calls (`filter_result=failed`, filtered in the database).

Not implemented in this task (TASK-147 is a content review). The proposed direction is in
`docs/tasks/TASK-147/SUGGESTIONS.md` §4: either rename the tab **Provider alerts** and state the
window and the thresholds it uses, or feed it the real failure list from the call log so that
"failed" means one thing everywhere.

Whichever way it goes, the three buckets must be named separately — failed (324), unusable (92) and
wasted (416) — and the tab's empty-state string must not claim "no errors" when calls failed.

## Verification

1. Open `/monitoring/ai-usage?tab=errors` with the default 24 h period on a team with failures in
   the window. The tab must show the failures, or be named and scoped so that it clearly is not
   the failure list.
2. Cross-check the number on the Overview ("N failed calls"), the Usage tab's *Errors* column and
   `GET /server/ai/usage?hours=24&team_id=<team>&group_by=category` → `totals.errors` — they must
   be the same quantity, or each must be labelled with its own name.
3. Change the period to "1 h" and to "7 d": the Errors tab must either follow the period or say
   which window it covers.
4. The header badge must show a non-zero count when calls failed.
