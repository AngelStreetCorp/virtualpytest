# BUG-0900 — A campaign aborted by a scheduler restart stays "running" for ever

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0900                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend (host deployment scheduler)                          |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/e76-orphaned-campaign-execution`             |

---

## Symptom

One campaign run keeps three rows: `deployment_executions`, `script_results` and
`campaign_executions` (the one the nightly report reads). When the host scheduler restarted
while a campaign ran, its startup recovery closed the first two and left the campaign row
`status='running'`, `completed_at=NULL`, `error_message=NULL` for ever, while the deployment
row said `failed` / `Execution aborted - scheduler restarted`. A reader could not tell a dead
night from a live one. Measured on the live database (2026-10-25): `status='running'` matched
exactly one row in the whole table (6,441 `completed`, 443 `failed`), and that row was this one.

## Root cause

`_mark_stale_execution_failed` closed the deployment row and its script row but never the
campaign row. The startup recovery also only looks for deployment executions still `running`,
so a campaign whose deployment row an earlier restart had already closed was never revisited.
The link needed to find the campaign row already exists: the executor writes
`metadata->>'deployment_execution_id'`, present on 571 of 571 rows since 2026-10-01 (only
Feb–Mar 2026 rows predate the key). `reconcile_stale_campaign_executions` has no production
caller and is out of scope here.

## Fix

`_mark_stale_execution_failed` now also closes the campaign row found through that link:
`status='aborted'`, `success=false`, `completed_at`/`updated_at` = the deployment row's
timestamp, `error_message` = the deployment's reason. It writes only while the row is still
`running`, inside the deployment's `team_id` and on this host, and never touches `executed_by`
(a uuid column). A failure is logged and never stops the startup cleanup. A new
`_sweep_orphaned_campaign_executions`, run at startup after the stale cleanup, closes campaign
rows still `running` whose linked deployment execution is already closed. Rows without the
link are left alone; nothing is closed by age.

## Verification

`tests/backend_host/test_orphaned_campaign_execution.py` (8 cases: close, no link, already
closed, execution still running, startup sweep, other team, no metadata key, write failure).
Seven of the eight fail on the pre-fix tree with `AssertionError`.

## Evidence

Live row `campaign_exec_1792888801_b986ca08` (`nightly_tc_android`, 2026-10-25 00:40Z):
campaign `running`, deployment `failed` at 00:40:37. The sweep closes it on the host's next
restart; no manual edit.
