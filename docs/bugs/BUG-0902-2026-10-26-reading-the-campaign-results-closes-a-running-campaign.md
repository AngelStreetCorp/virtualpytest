# BUG-0902 — Reading the campaign results closes a running campaign as "failed"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0902                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | shared (campaign executions database module)                 |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/e78-read-path-closes-running-campaign`       |

---

## Symptom

The dashboard's campaign tab polls the server every 20 seconds, and that read repairs rows. One
repair closed a campaign that was still running as `status='failed'`, `success=false`, message
"Campaign execution became stale before completion", `completed_at` = the reader's clock. The
nightlies are created with `timeout_minutes: 120`; with the 300-second grace the threshold is
**125 minutes**, and their measured durations are **125.7 to 170.3 minutes**. In the last 30 days
**51 of 688** rows configured with `timeout_minutes=120` ran past it (all 13 `nightly_ds_web`
runs, 8 of 10 `nightly_vs_android`, all 4 `nightly_vs_switch`, all 3 `nightly_ds_switch`, and
others). From minute 125 to the end of each run the row read "failed" while it was still going;
the nightly watcher counted it as done and failed. The executor's final write usually corrected
it afterwards. Two rows never were: `labox_tv_smoke` (25 of 25 scripts succeeded) and
`TP_001 sanity` (1 of 1) were recorded `failed` with `completed_at = 2026-09-21 07:15:46Z`, the
reconcile's clock.

## Root cause

`get_campaign_results()` called `reconcile_stale_campaign_executions(team_id)` on every read. For
a row whose scripts were not all final it decided `stale = now - started_at > timeout + grace`:
a wall-clock age against a threshold the product's own campaigns exceed, then wrote the generic
failure with `completed_at = now`. Age is not evidence that the worker is gone. A campaign with
fewer script results than `script_configurations` also fell into that branch even when every
result it had succeeded. Every read also did a team-wide select plus a per-row `script_results`
fetch.

## Fix

All in `shared/src/lib/database/campaign_executions_db.py`.

- Staleness is now **silence**, not age: the latest of the campaign start and each linked script
  result's `started_at`, `updated_at` and `completed_at`. A row is closed only when that silence
  exceeds `timeout_minutes` + grace (unchanged: 300 s). A nightly at minute 170 whose scripts keep
  reporting is left alone.
- A close is `status='aborted'` (the host sweep's verdict, BUG-0900), `success=false`,
  `completed_at` = the last activity (not the reader's clock), and a message that names the
  silence, the limit and the counts, e.g. "no activity for 200 min (limit 125 min); 1 of 2 expected
  script results recorded, 1 succeeded".
- The silence rule applies only to unfinished campaigns and only past the limit.
- `get_campaign_results` repairs at most once per team per 5 minutes
  (`RECONCILE_MIN_INTERVAL_SECONDS`), not on every poll.
- The all-scripts-final branch (verdict from the script results) is unchanged and independent of age.

Neither value moved: `timeout_minutes: 120` in `create_campaigns.py` and the 300 s grace stay,
because the rule no longer compares age with them. Existing rows are not edited.

**History is not repaired.** `labox_tv_smoke` and `TP_001 sanity` keep the verdict they have. The
fix stops new wrong verdicts only.

`shared/` is loaded by both the host and the server, so the change needs a host leg and a server
leg deployed.

## Verification

`tests/test_campaign_reconcile_staleness.py` (10 cases). On the pre-fix tree 6 fail with
`AssertionError` (running row written; 170-minute nightly closed; read changes a field; close
carries `now` and the generic message; fewer-results message; repair on every read). Four pass
before the fix by design: an abandoned row still ends closed, the executor's final write wins, a
row with no script results costs no fetch, and a finished campaign younger than the limit is still
closed by its script verdict. `tests/test_skipped_outcome.py` and
`tests/test_campaign_skipped_verdict.py` still pass.

## Evidence

Counts from the live `campaign_executions` table, last 30 days (read only, nothing edited): 688
rows with `timeout_minutes=120`, 51 beyond 125 minutes, longest 170.3 min (`nightly_ds_switch`).
