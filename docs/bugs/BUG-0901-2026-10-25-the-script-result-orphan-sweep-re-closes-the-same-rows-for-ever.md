# BUG-0901 — The script_result orphan sweep re-closes the same rows for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0901                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend (host deployment scheduler)                          |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/e77-script-result-orphan-sweep`              |

---

## Symptom

Every host that runs the scheduler logged, every five minutes, `Closed N orphaned script_result
row(s)` with the same N. One host's log carried 609 such lines since 2026-10-22 23:17, the count
climbing from 25 to 31 as more runs died. The sweep closed the rows nobody had closed, then
closed the rows it had already closed, for ever.

Three effects, measured on the live database and the host logs (2026-10-25):

1. The log line lied: "Closed 31" meant 31 rows that were already closed.
2. `completed_at` was overwritten every cycle with the sweep's own clock, so "when did this run
   end" rolled forward every five minutes (31 rows on one host shared one identical timestamp).
3. Write churn: 164 rows rewritten every five minutes across the fleet, about 47,000 UPDATEs a
   day on `script_results`, each a new row version.

## Root cause

`_sweep_orphaned_script_results` selected and updated rows with `execution_time_ms IS NULL`, but
the update writes `completed_at`, `updated_at`, `success` and `error_msg` and never
`execution_time_ms`. A row the sweep closed therefore still matched the next cycle's select and
update, and was counted again. The filter could never exclude what the sweep itself had done.

Of the 164 rows with `execution_time_ms IS NULL`, 31 were still placeholders and 133 were already
closed. Two independent tests agree on exactly the same 31: `error_msg IS NULL`, and
`completed_at - started_at < 1 s`. A placeholder's `completed_at` is a separate `now()` call, a
few microseconds after `started_at`, so an equality test would match nothing.

## Fix

Only `backend_host/src/services/deployment_scheduler.py`. The select now also requires
`error_msg IS NULL`, and the candidates are confirmed in Python as placeholders
(`completed_at - started_at` under one second). The update is guarded with `execution_time_ms IS
NULL` and `error_msg IS NULL`, so a row closed by someone else between select and update is not
overwritten, and `closed` counts the rows the write actually changed. Grace period, message,
`success=False`, host scoping and the empty-cycle silence are unchanged. `shared/` is untouched.

The 133 rows already closed are not repaired: their `completed_at` carries a rolling sweep
timestamp and the true close time is gone. The fix stops the rolling; it cannot restore the truth.

## Verification

`tests/backend_host/test_orphaned_script_result_sweep.py` (8 cases: first close with typed values,
second cycle untouched, already closed by the sweep, closed by a successful run, younger than the
grace period, other host, count is rows closed, closed between select and update). Four fail on
the pre-fix tree with `AssertionError`: second cycle, already closed by the sweep, count, and
closed between select and update.

## Evidence

Live: 164 rows with `execution_time_ms IS NULL`, 31 placeholders, 133 closed; 609 log lines on one
host since 2026-10-22 23:17:07. After deploy the sweep logs only when it closes a row for the first
time.
