# BUG-0284 — A successful standby measurement reported "Execution summary not available"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0284                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | High — every standby run that got a KPI result lost its summary, so the measured wake time never reached the report |
| Status    | Fixed (pending deploy)                                            |
| Area      | `test_scripts/tv/standby_measurement.py` · `shared/src/lib/executors/script_executor.py` |
| Fixed in  | Unreleased                                                        |
| Related   | [BUG-0204](BUG-0204-2026-10-01-standby-wake-already-awake-blamed-kpi.md), [BUG-0199](BUG-0199-2026-09-30-three-more-host-callbacks-swallow-401.md) (early-release logging) |
| Commit    | this commit                                                       |

---

## Symptom

Customer run, `standby_measurement`, 1 iteration: the report shows success, but its
Execution Summary section says "Execution summary not available — this may be from an
older script run". The log has the measurement and then:

```
📊 [standby_measurement] Wake KPIs: 1/1 successful (0 skipped, 0 failed)
❌ [standby_measurement] Unexpected error: _append_direction_metrics() takes 3 positional arguments but 4 were given
SCRIPT_SUCCESS:true
```

## Cause

`standby_measurement` reuses `kpi_measurement._append_direction_metrics` to render the
KPI block. `a18a83bbc2` (2026-07-29) dropped that helper's 4th parameter (the
pad-to-N-iterations count — a multi-hop path legitimately has different row counts per
edge). The standby script kept passing `args.iterations`.

The call runs in `main()`'s `finally`, while building `context.execution_summary`, so
the `TypeError` escaped before the summary was assigned. The measurement and its DB row
were fine; only the report lost them. Runs with no KPI rows skipped the call, which is
why it only showed up once wakes were measured.

## Fix

- Call the helper with its current three arguments.
- Same change, separate symptom: the early device release logged "Requested early device
  release" on any HTTP 200. The server answers 200 with `released: false` when a user's
  Take Control session (`manual_control`) owns the lock and, by design, leaves the device
  with that user. The host now logs that the release was not done and why, so "the device
  is still in control after the run" reads as intended rather than as a leak.

## Verification

- `python3 -m py_compile` on both files.
- The helper called exactly as the script now calls it, with one successful row, renders
  the `📈 KPI Metrics (…)` block (header, ✅ 1/1, min/max/avg, per-iteration line).
- `git grep "_append_direction_metrics("`: the two remaining callers both pass three
  arguments.
- Not yet re-run on the customer device.
