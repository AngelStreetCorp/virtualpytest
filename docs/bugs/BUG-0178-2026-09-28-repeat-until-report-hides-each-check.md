# BUG-0178 — A failed "press until" step showed every iteration as ✅ 0ms and linked no comparison report

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0178                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / reports / frontend                            |
| Fixed in  | build 90145 |
| Commit    | `757d3e4ba`, `eeec22af1`                                     |

---

## Symptom

A navigation step whose action is a `repeat_until` ("press DOWN until the Standby row
appears, max ×6") failed in a script run with:

```
❌ press_key(DOWN) [until appears (all), max ×6, wait:1000ms]: repeat_until condition not met after 6 iteration(s) (condition=appears, match=all)
✅ Iteration 1/6: Success (0ms)
...
✅ Iteration 6/6: Success (0ms)
```

- Every iteration read **✅ Success (0ms)**, which looks like the loop neither waited nor checked.
- The script report's step showed only `Failed Actions: press_key (6/6 iterations): repeat_until
  condition not met…` — no link to the comparison (source frame vs reference) of any check, so
  there was no way to tell whether the highlight never reached the row or the image match failed.

## Root cause

In `backend_host/src/services/actions/action_executor.py` (`_execute_single_action`):

1. The iteration row was appended **right after the key press**, before the settle wait and the
   single-frame check. Its `success` was the press being sent, and `execution_time_ms` timed only
   the press (~0 ms). The wait and the check did run (the step took 8.3 s for 6 × 1000 ms waits),
   but nothing about them was recorded.
2. The repeat_until verification report was only built when `report_repeat_until` was set, which
   only the interactive Edge "Run" does. Script / testcase runs never got one — not even on
   failure — and only the decisive check was ever kept.

## Fix

- `action_executor.py`: each repeat_until iteration now records `press_ms`, `wait_ms`, `verify_ms`,
  `condition_met` and the check's message; `execution_time_ms` covers the whole press → wait → check
  cycle. When the cap is reached, every check gets its own verification report
  (`iterations[i].verification_report_url`), and the action result carries the last one. Passing
  loops still only report in interactive Edge runs.
- `shared/src/lib/utils/report_step_formatter.py`: the step's action line links the comparison
  report, and a repeat_until action lists one row per iteration (press / wait / check outcome and
  message) with its own report link.
- `frontend/src/hooks/actions/useAction.ts`: the live Run log shows the check outcome per iteration
  instead of the press outcome.

## Verification

Run a script whose navigation hits a repeat_until edge that cannot reach its target (e.g. a
reference that never matches). In the script report, open the failing step: the action line shows
**📊 View comparison report ↗**, and below it six rows
`✗ Iteration N/6: press ✓ (…ms) · wait 1000ms · check not met (…ms) - <message>`, each with its own
report link opening that check's frame vs the reference. The Edge Run panel log shows the same
per-iteration check outcome.
