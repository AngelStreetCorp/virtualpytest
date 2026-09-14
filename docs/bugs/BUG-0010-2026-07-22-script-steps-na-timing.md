# BUG-0010 — Host-diagnostic script report steps show "Start: N/A End: N/A Duration: 0s"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0010                                                     |
| Reported  | 2026-07-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | shared / test_scripts                                        |
| Fixed in  | build 8713                                                   |
| Commit    | `ce9ba8ae6`                                                        |

---

## Symptom

In the test report, every step of the `gw/*` host-diagnostic scripts rendered
`Start: N/A End: N/A Duration: 0s` — even when the step clearly took real time
(e.g. an nslookup measured at 43.3ms in the same step's verification detail).
Affected `dns_lookuptime`, `ookla_speedtest`, and `superping`.

## Root cause

The report step formatter reads `start_time` / `end_time` (`HH:MM:SS` strings)
and `execution_time_ms` (int) off each step dict, defaulting to `N/A` / `N/A` / `0`
when absent (`shared/src/lib/utils/report_step_formatter.py`).

Executor-driven scripts (goto/validation/zap) get these fields for free because
`NavigationExecutor`/`ActionExecutor` time each step. But host-diagnostic scripts
assemble the step dict by hand and hand it to `ScriptExecutor.record_step_immediately()`,
which only stamped `step_number` + a raw `timestamp` and never populated the timing
fields. So every hand-built step rendered N/A.

## Fix

Centralized timing formatting in the executor instead of per script:

- `shared/src/lib/executors/script_executor.py` — new `_normalize_step_timing()`,
  invoked by `record_step_immediately()`. Callers may pass `start_time`/`end_time`
  as raw epoch floats (what `time.time()` returns); it formats them to `HH:MM:SS`
  and derives `execution_time_ms`. Values already given as strings pass through
  untouched (backward compatible), and steps with no timing are left as-is.
- `test_scripts/gw/dns_lookuptime.py`, `ookla_speedtest.py`, `superping.py` —
  pass `start_time`/`end_time` floats around the timed operations.

## Verification

Re-run any affected script and open its report: each timed step now shows real
`Start` / `End` clock times and a non-zero `Duration`. Existing stored reports are
unchanged (fix applies to new runs only).
