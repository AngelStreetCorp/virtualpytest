# BUG-0732 — The 30-day AI usage view reports a 90.4 % failure rate, and nothing says 99 % of it is the fixed BUG-0492 storm

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0732                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend / AI usage page                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/monitoring/ai-usage`, switching the period to **30 d** makes the page read as catastrophically
broken. Measured live on 2026-10-20 for one team, same API, three periods:

| Period | Data source | Calls | Failed | Failure rate |
|---|---|---|---|---|
| 24 h | `calls` (per-call log) | 4,647 | 314 | 6.8 % |
| 7 d | `calls` | 27,294 | 3,574 | 13.1 % |
| **30 d** | **`rollup`** (`ai_usage_stats`) | **873,852** | **789,528** | **90.4 %** |

The daily series (`series` / `failed_series`, `step_s` = 86400) shows where the volume is:

| Day | Calls | Failed |
|---|---|---|
| 2026-10-07 | 2,129 | 9 |
| **2026-10-08** | **70,809** | **70,276** |
| **2026-10-09** | **228,573** | **228,573** (100 %) |
| **2026-10-10** | **181,679** | **181,679** (100 %) |
| **2026-10-11** | **220,693** | **220,692** |
| **2026-10-12** | **82,363** | **82,306** |
| 2026-10-13 … 2026-10-20 | 446 … 6,846 | normal |

- The five days **2026-10-08 → 2026-10-12** carry **784,117 calls (89.7 % of the 30-day volume)
  and 783,526 failures (99.2 %)** at a **99.9 %** failure rate.
- Excluding those five days the rollup shows **89,737 calls at 6.7 % failures** — the same rate
  the call log reports for the last 24 h.
- The last seven days of the rollup (2026-10-14 → 10-20: 27,580 calls / 3,843 failed) match the
  7-day call-log numbers (27,294 / 3,574) to within live drift.

Nothing on the page marks those days. The Overview, the Usage total row, the Providers counts and
the budget all read as if 90 % of the platform's AI calls are failing now.

## Root cause

**The numbers are right; the page gives them no context.** The five days are the no-credit storm of
[BUG-0492](BUG-0492-2026-10-12-ai-no-credit-402-retried-on-every-call.md): OpenRouter answered
HTTP 402 and every caller sent the next request anyway. `vision.alert_triage` alone failed about
9,000 times an hour on `qwen3-vl-8b` (117,141 calls and 117,120 errors in one day) until the
back-off shipped on 2026-10-12 around 12:00 UTC. Those calls happened, and the rollup counted them
correctly.

The TASK-147 reviewers first read the five days as a backfill artefact; BUG-0492 shows otherwise.

The 30-day view reads the hourly rollup (`ai_usage_stats`), not the per-call log (`ai_calls`):

```python
self.source = 'calls' if self.hours <= CALLS_MAX_HOURS else 'rollup'
# backend_server/src/routes/server_ai_routing_routes.py:434
```

Two things then go wrong on the page:

1. **One fixed incident becomes the headline.** A 30-day total is dominated by whatever burst sits
   in the window, and the page shows only the total: no daily axis, no incident marker, no "with /
   without" figure.
2. **The definition of "wasted" changes.** In the call log, `wasted = errors + unparsed +
   truncated` (416 against 324 failures). The rollup has no `parse_total` / `parse_ok_n` /
   `truncated` columns, so there `wasted == errors` exactly (789,528 = 789,528), on every day,
   not only the storm days. The same word, two definitions, depending only on the period picked.

## Fix

**Fixed 2026-10-21 (TASK-147 round 2):** on the 30-day view the fourth tile reads *Failed* (the rollup cannot tell waste), the chart names days with ≥ 90 % failures at ≥ 5× the median volume "Incident 08/10–12/10", and the tile's caption is the failure rate without those days. The rows are kept.

Not implemented in this task (TASK-147 is a content review). Proposed in
`docs/tasks/TASK-147/SUGGESTIONS.md` (step 0, Q4):

1. **Show the incident.** Draw the daily series on the 30-day view and mark the storm days, and
   show the window's failure rate with and without them (or a note that most failures are one
   fixed incident, linking BUG-0492).
2. **Make the 30-day view announce what it is**: label it "Aggregated (hourly)", say that "wasted"
   means "failed" there, and disable the four grouping dimensions and two filters the rollup cannot
   answer, with a visible reason rather than a silent loss.

**Keep the rows.** They are the only record of the incident. Removing or excluding them in
`ai_usage_stats` would be deleting shared history and needs the owner's decision.

## Verification

1. `GET /server/ai/usage?hours=720&team_id=<team>&group_by=category` still returns the five storm
   days unchanged.
2. Open the page at "30 d": the storm days are visibly marked, and the failure rate without them
   (≈ 6.7 %) is shown next to the total rate.
3. At 30 d the page states that "wasted" counts failed calls only.
