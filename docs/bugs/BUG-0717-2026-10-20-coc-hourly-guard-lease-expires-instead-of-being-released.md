# BUG-0717 — The hourly Clash of Clans run held the phone with an expired lease instead of releasing it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0717                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | platform / lease guard, game / clash of clans (TASK-100)     |
| Fixed in  | build 90145 |
| Commit    | `92eec1df8`                                                  |

---

## Symptom

The guard lease that protects the CoC phone (`node1-vpt/vpt-pi1/device1`, agent
`codebox:coc-hourly-run`) **expires** instead of being **released**: the registry recorded
`lease:expired` at 09:44 and 10:44 UTC on 2026-10-20, while every run before 07:18 released it.
The phone stayed leased for about 45 min after the run was over, and other agents could not claim
`device1` in the meantime.

## Root cause

Three faults, all of them the same story: **the guard's time assumptions no longer match the
run**.

1. **The lease TTL was shorter than the run.** The guard (`coc-run-lease.sh`, a systemd user unit on
   codebox) claimed the lease with `--ttl 45` and then waited 2700 s (45 min) for the run's
   `completed_at`. A CoC LLM run takes **20-60 min** (60-90 model steps at ~35 s each, measured in
   the run ledger: 67, 72, 80 and 90 steps for the runs of 04:00-09:00 UTC). The 09:00 UTC run
   alone ran from 09:00:00 to 10:00:04. So the TTL ran out in the middle of the run: the registry
   reaped the lease (`expired`, `by=system`, `reason=ttl`) and the guard's own release, a few
   seconds later, found a lease that was already gone. The registry therefore never saw a release
   at all - only the expiry.

   Lease events (2026-10-20): `granted a2f89161 08:59:05 -> expired 09:44:05 (held 45, by=system)`,
   `granted 45c5c03c 09:59:05 -> expired 10:44:05 (held 45, by=system)`, against
   `granted 821eddf5 06:59:05 -> released 07:18:14 (held 19, by=holder)` for the last good run.

2. **The guard lied about the release.** `release()` ran `vpt-lease release` with its output
   discarded and always wrote "released" to the log, so the log read `09:44 timeout, releasing` /
   `09:44 released` while the registry recorded no release at all. Two other paths had the same
   shape: the service's `TimeoutStartSec=2850` (47.5 min) would have killed the guard before any
   longer wait could release the lease, and a *skipped* execution (the platform did not start the
   run) never sets `completed_at`, so the guard held the lease for its whole wait budget for a run
   that would never start.

3. **The hourly trigger can be dropped, and then there is no run to wait for.** The deployment
   scheduler runs the whole script inside the APScheduler job, and a job has `max_instances=1` by
   default: when the previous run is still going, the next trigger is **dropped** - the Pi's
   journal at 12:00:00 local (10:00:00 UTC) says `Execution of job "DeploymentScheduler.
   _execute_deployment (trigger: cron[...hour='*', minute='0'])" skipped: maximum number of
   running instances reached (1)`. No execution row is created for that hour, so the guard waited
   for a run that never started and the lease expired at 10:44 with the phone in fact free since
   10:00.

A fourth fault made the data wrong rather than the lease: the host scheduler called a CoC run
**stale after 30 min** (`max_age_s = 1800`), on the assumption that a CoC run is at most ~15 min.
A healthy 60 min run therefore got marked failed (`Execution timed out - ran for 0.5 hours`, the
00:00 UTC run) and the next run could be started on top of it.

## Fix

- **`scripts/agent/coc_run_lease.py` (new)** - the guard, now in the repo instead of only on codebox:
  - **renews** the lease every 5 min while a run is on the phone (TTL stays 45 min), so the lease
    cannot expire under the guard, whatever the run lasts;
  - **releases on every exit path**, including SIGTERM (the signal handler unwinds through the same
    `finally`), and releases a lease that a dead guard left behind at the next start;
  - waits for the **phone to be free**, which covers the three ways an hour ends: the run finished
    (`completed_at`), the platform skipped the trigger, and the trigger was dropped. When the hour
    produced no run at all, the lease goes back within a couple of minutes instead of being held
    for the whole wait budget;
  - **reports the release honestly**: the exit code says what happened (0 released, 3 the claim was
    refused, 4 the run overran the wait budget, 5 the release failed) and the log only says
    "released" when the registry took it.
- The **systemd unit** (`coc-run-lease.service`, `coc-run-lease.timer`) stays on codebox, where the
  guard runs: the integration lane refuses any diff that touches a systemd unit (its merge policy
  calls a `.service`/`.timer` a sensitive path), so the unit is written out in
  `docs/agent/ai/COC_LLM_BUDGET.md` instead of being committed. Its `TimeoutStartSec` goes from
  2850 (47.5 min) to **7800 s**, so systemd cannot kill the guard before it frees the lease.
- **`backend_host/src/services/deployment_scheduler.py`** - the stale threshold for CoC LLM runs
  goes from 30 min to **90 min**: a healthy 20-60 min run is no longer marked failed
  (`Execution timed out - ran for 0.5 hours`, the 00:00 UTC run), and the next run is no longer
  started on top of a live one.
- **`guarded_hour()` (follow-up, 2026-10-20 12:53)** - the guard took the hour it had to wait for
  from the moment it started, so a guard started by hand in the middle of an hour (12:53) took the
  hour that had just passed (12:00) as its hour: that trigger was long gone, so the guard found
  the phone free **31 s later** and released the lease, seven minutes before the game of the next
  hour (13:00) began - the run of 13:00 would have gone unguarded. The guarded hour is now the
  trigger that is still ahead of the claim, or the one that fired within the claim window (the
  phone was busy, the claim was refused and retried). The release gate follows it, so the guard
  never frees the phone before the run it protects had its chance.

## Verification

- Unit tests (`tests/scripts/test_coc_run_lease.py`, 21 tests): the guard renews the lease while a
  run outlives the TTL and still releases it, it releases when the trigger was dropped, it waits
  for a previous run that is still going, it releases when the wait budget runs out, it does not
  touch another agent's lease when the claim is refused, it releases a lease left by a dead guard,
  and it keeps the lease when the history cannot be read. The stale-execution check
  (`tests/backend_host/test_deployment_scheduler_stale.py`) pins the 90 min threshold.
- Live, on the phone: the 11:00 UTC run held the lease from 10:59:05 and **released it at
  11:35:05** (`released`, `by=holder`, held 36 min) - the run ended at 11:34:42, so the lease went
  back with the run instead of expiring 45 min later. The registry events of the two broken hours
  before it read `expired` / `by=system` / `reason=ttl` at 09:44:05 and 10:44:05.
- The shipped guard (`scripts/agent/coc_run_lease.py` on main, installed as the `coc-run-lease`
  systemd user unit on codebox) took over at 12:09 UTC and went through the 12:00 UTC run the same
  way. Its **first** start at 11:59 UTC failed with `216/GROUP`: a *user* unit cannot set
  `User=`/`Group=` (those work in a system unit only), so the unit ran without them and the 12:00
  hour was unguarded for nine minutes until it was fixed.
