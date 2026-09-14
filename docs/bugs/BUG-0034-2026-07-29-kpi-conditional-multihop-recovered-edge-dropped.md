# BUG-0034 — KPI report drops the recovered hop of a conditional multi-hop path (reports FAILED with "no KPI rows")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0034                                                     |
| Reported  | 2026-07-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (conditional multi-hop KPI runs report FAILED and hide a measured hop) |
| Area      | test_scripts/kpi_measurement.py — summary attribution & rendering |
| Fixed in  | build 8713                                                   |
| Commit    | `a18a83bbc`, `817a30910`                                     |

---

## Symptom

A `kpi_measurement` run of `apps_disney → disney_home` on `host7` reported **FAILED**
even though the device reached `disney_home`. The path actually crosses a conditional intermediate
node — `apps_disney → disney_profile → disney_home` — and the summary showed only the first hop as
a skip plus an error, with the real second-hop measurement nowhere to be seen:

```
⚠️  Source recovered to conditional sibling 'disney_profile' … measured from the sibling.
📈 KPI Metrics ([TC523] Open app Disney):
   ✅ 0/1   ⚠️ 1/1 skipped
   1. ⚠️ Skipped - Destination Verification failed  📊 View failure report ↗
🎯 Result: FAILED
❌ Error: Navigations ran but produced no KPI rows for 'disney_profile → disney_home'
   (3 unrelated KPI row(s) recorded in the window).
```

The user expected **both** hops' KPIs — `apps_disney → disney_profile` and
`disney_profile → disney_home` — since both lie between source and target.

## Root cause

The executor already records **one `execution_results` row per traversed hop**, each under its own
`action_set_id` (`navigation_executor.py` per-step recording + KPI queue). When `disney_home`
verification fails and the device is on the conditional sibling `disney_profile`, the executor
splices a recovery path and traverses `disney_profile → disney_home`, writing a **positive** KPI row
under that edge's `action_set_id` and tagging the step `is_recovery=True`
(`navigation_executor.py:1701-1725`). So the data existed.

The KPI **script** discarded it. On source recovery it reassigned `selected_action_set_id` to the
`disney_profile → disney_home` edge but **never added that id to `forward_action_set_ids`** — the
set every summary/verdict filter keys on. The recovered hop's row therefore failed both the DB-poll
count and the final `filtered_kpi_results` filter and was reported as one of the *"unrelated"* rows,
so:

1. the verdict saw 0 successful forward measurements → **FAILED**, and
2. the summary collapsed all "forward" ids into a **single** block, so even ids that were present
   rendered under one label instead of one block per traversed edge.

## Fix

All in `test_scripts/kpi_measurement.py` (script-only — no executor or Grafana change):

- **Attribute the recovered continuation edge.** On source recovery, the tree-resolved
  `disney_profile → disney_home` `action_set_id` is added to `forward_action_set_ids` /
  `relevant_action_set_ids`, so its positive row counts toward the verdict and is shown. The run
  now reports **SUCCESS (recovered)**.
- **One KPI Metrics block per distinct traversed edge**, grouped by `action_set_id` and ordered by
  first measurement, instead of collapsing every forward hop into one block. The skipped conditional
  edge and its recovered continuation now each get their own block.
- **Per-hop titles.** A new `action_set_id → {label, kpi_name, from, to}` map (enriched from the
  live `navigation_path`) titles every hop by its own transition — appended in parentheses so hops
  are distinguishable even when the operator reuses one KPI Display Name across the whole flow.
- Iteration rows render the measurements actually recorded (no pad-to-N phantom "Missing" rows,
  since different hops legitimately have different counts).

Resulting summary:

```
📈 [TC523] Open app Disney (apps_disney → disney_home):
   ⚠️ Skipped - Destination Verification failed (landed on sibling 'disney_profile')  📊 ↗
📈 [TC523] Open app Disney (disney_profile → disney_home):
   ✅ 4210ms (4.21s)  📊 ↗
🎯 Result: SUCCESS (recovered)
```

## Notes / scope

The first hop stays a **skip** of `apps_disney → disney_home` (the executor records the attempted
edge as a destination-verification skip when it lands on the sibling — it does not measure
`apps_disney → disney_profile` positively). Surfacing a positive first-hop time would require an
executor change to record the sibling landing as a positive traversal, which was deliberately left
out of this fix.

## Follow-up: DB poll exited before the recovered measurement landed (`817a30910`)

The attribution fix above was necessary but not sufficient — the first post-deploy run on
`host7` still reported FAILED. The `vpt-kpi` worker logs (now device/edge-stamped, see the
logging commit) showed why: the two hops are two separate KPI requests processed **sequentially by
the single worker**:

- `12:35:44` — `apps_disney → disney_home` (action_set `apps_disney_to_disney_profile_…`) →
  `⏭️ Skipping scan: live verifier already failed` → skip row stored **immediately**.
- `12:36:00` — `disney_profile → disney_home` (action_set `disney_profile_to_disney_home`) →
  `✅ 6515ms` stored **~15s later**.

The script's DB poll counted **any** row under a forward action_set toward `fwd_count`. The fast
skip satisfied `fwd_count == expected_forward (1)` on the very first poll, so the poll exited and the
verdict ran ~15s before the real measurement was stored — hence FAILED + "no KPI rows", the 6515ms
row surfacing afterwards as "unrelated".

**Fix:** track a `recovered_forward_ids` set (the edge actually measured, populated by the
source-recovery and both fallback branches) and require a DB row under every such id before the poll
declares the forward legs complete. Normal (non-recovery) runs keep an empty set → unchanged
behaviour.

## Verification

`python3 -m py_compile` clean (both commits). Root cause confirmed directly against the deployed
`host7` `vpt-kpi` journal (skip stored 12:35:44, real 6515ms measurement stored 12:36:00).
Full end-to-end validation is re-running the `apps_disney → disney_home` KPI measurement after
deploying `817a30910` — expecting the poll to wait for the `disney_profile_to_disney_home` row, both
hops shown, and **SUCCESS (recovered)**.
