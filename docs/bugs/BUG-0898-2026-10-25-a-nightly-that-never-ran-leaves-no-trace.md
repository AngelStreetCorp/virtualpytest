# BUG-0898 — A nightly that never ran leaves no trace

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0898                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | backend (deployment scheduler / campaign layer)              |
| Fixed in  | build 90145 |
| Commit    | `1dd53be11606b050afdcae74601a6a7dba5704cf`, `1103fb82e65100d3ef0d63c96c3be7a35224389a`             |

---

## Symptom

**The nightly campaigns did not run every night.** They are not supposed to be flaky: the nightlies
carry the cron `30 0 * * *` and are due every night at 00:30 UTC. On 2026-10-24, of the **ten**
deployments due at that moment, **five were skipped** — and a skipped nightly leaves **nothing at
all** in the place a reader looks.

The skip itself is recorded. The deployment layer writes a `deployment_executions` row with
`status='skipped'` and a reason. The campaign layer records **nothing**: a skipped deployment
never produces a `campaign_executions` row. The nightly campaign results, and the nightly report
that reads them (`scripts/nightly_campaigns/poll_results.py`), read the **campaign-level** rows —
so a reader cannot tell *the nightly ran and found nothing* from *the nightly never ran*. The
deployment's own `last_executed_at` does not advance either, so no fact that says "this one was
skipped" exists anywhere a report looks.

**Three nightlies, one device, one survivor.** The three web nightlies — `nightly_ds_web`,
`nightly_tc_web` and `nightly_vs_web` — all carry the cron `30 0 * * *` and all run on the **same
device**. They therefore serialise against each other through the device lock, and the one that
finds the device busy is dropped for the whole day: the log says it "will retry next trigger",
which means tomorrow. Over six days (2026-10-19 → 2026-10-24) **exactly one** of the three ran per
night, and which one survived was a race for the device lock, not a schedule — `nightly_vs_web`
last executed on **2026-10-14**, ten days before this defect was written up.

The same "Device busy" skip silently eats the hourly `TP_001 sanity` deployment several times a
day as well.

## Root cause

**The skip was written on one side of the platform and read on the other.**

- `backend_host/src/services/deployment_scheduler.py` writes every skip **only** to
  `deployment_executions` — `status='skipped'`, `success=False`, `skip_reason=<the reason>` — and
  returns. There is one such write per skip site: the deployment's own constraints
  (`_should_execute`), the device queue full, the device busy (recurring cron), the device locked
  by another owner, and the device still running.
- The campaign is only resolved **later** in the same method: the DB campaign lookup
  (`get_campaign_by_name`) and the `CampaignExecutor` that writes `campaign_executions` both live
  past every one of those `return`s. A skipped deployment therefore never reaches the campaign
  table — the skip is a fact about the deployment, and the campaign layer never hears of it.
- The nightly report (`scripts/nightly_campaigns/poll_results.py`) counts a campaign as done only
  for the statuses `completed` / `failed` / `aborted`, and renders its flag from `status` and
  `success`. A skipped campaign would have to read as skipped in **both** places, and must not be
  counted as a failure: a night where nothing ran is not a night where something broke.
- `campaign_executions.status` also carries a Postgres **CHECK constraint** that accepts only
  `pending`, `running`, `completed`, `failed`, `cancelled` and `aborted`. The value `skipped` is
  rejected by the database, so a skip cannot be written as a status: the constraint is left
  untouched and the skip travels in a flag, while the status column keeps its meaning.

## Fix

- A skipped **recurring** deployment now leaves a **campaign-level record** that reads as skipped
  and carries the reason. The deployment's own campaign name is resolved with the **same rule the
  execution path uses**, so the record lands on the same campaign the run would have used — the
  nightly report counts the night it is looking at.
- The **busy**, the **locked** and the **queue-full** skips all leave that same kind of record, so
  the three reasons behave identically instead of each having its own invisible path.
- The nightly report counts a skipped campaign as **terminal** and shows it as **skipped**, not as
  a failure: the night that never ran is not a night that failed.
- The log line now says the run was **skipped** and **will not be retried today**, instead of the
  misleading "will retry next trigger" — which is what made a whole night of silence read as a
  temporary hiccup.
- A recurring deployment skipped because the device is busy is **retried inside its own trigger
  window**: bounded attempts, a deadline that fits inside the window, and no two executions of the
  same deployment at once. The three nightlies that share one device no longer lose each other.
- The `campaign_executions.status` CHECK constraint is **left untouched**: the live table accepts
  only `pending` / `running` / `completed` / `failed` / `cancelled` / `aborted`, and the value
  `skipped` is rejected by the database. The skip therefore travels in a **flag**:
  `setup/db/migrations/20261025a_campaign_executions_skipped.sql` adds `campaign_executions.skipped`
  (additive and idempotent — one column, no constraint touched), the row keeps a status the table
  accepts (`cancelled`), and the reason stays in `error_message` and `metadata.skip_reason`. The
  nightly report and the platform health read the **flag**, so a cancelled campaign keeps its own
  reading and only a flagged one reads as skipped.

## Verification

- **`tests/backend_host/test_nightly_deploy_skip.py`** (new) — run the two files with
  `timeout 300 pytest tests/backend_host/test_nightly_deploy_skip.py tests/backend_host/test_nightly_deploy_skip_flag.py -v`.
  The first covers the skipped campaign record itself, the report that reads it, and the retry
  inside the trigger window.
- **`tests/backend_host/test_nightly_deploy_skip_flag.py`** (new) — the check that was missing: the
  status the branch writes must be inside the set the live `campaign_executions` table accepts
  (`pending` / `running` / `completed` / `failed` / `cancelled` / `aborted`), the readers must key
  off the flag and not off the status word, and the record must survive a database that has not
  run the migration yet.
- Both files are the **negative control**: against the pre-fix commit (`e7c2c9cb9`) they **fail**
  (11 failed / 0 passed, every failure an `AssertionError`), and on the branch they **pass**
  (11 passed). A skipped campaign has to appear in `campaign_executions`, has to read as skipped in
  the nightly report, the status it carries has to be one the database accepts, and the three
  nightlies that share one device have to stop losing each other.
- The release-note entry for this fix is in `docs/release_note/README.md` under **Unreleased**.
