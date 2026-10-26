# BUG-0207 — One Run click left a second, "running forever" row behind the real run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0207                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | Medium — a phantom run sits in the table with no report, and can later re-run the script on the device unannounced |
| Status    | Fixed (pending deploy)                                            |
| Area      | `frontend/src/pages/RunTests.tsx`                                 |
| Fixed in  | build 90145 |
| Related   | [BUG-0118](BUG-0118-2026-09-16-api-callers-run-scripts-on-a-busy-device-instead-of-queueing.md) (server-side queue) · `5909580132` (a finished run releases its user's Take Control) |
| Commit    | this commit                                                       |

---

## Symptom

Customer, Run Tests, one `standby_measurement` on one STB, Start = Now, run once. The
executions table then shows two rows: one completed with report and logs (started 10:40,
2m 47s), and one ⏳ with no duration, report or logs, started 10:49 — six minutes after
the real run ended — that never finishes. Seen on two STBs (also 10:23 ✅ / 10:27 ⏳).

## Cause

A row in that table is one `deployment_executions` record, and one invocation of the Run
handler creates exactly one: a direct run when the device is free, or a one-shot queued
deployment (cron `0 0 1 1 *`, max 1) when `splitDevicesByLockState` reports it locked.
Two rows mean the handler ran twice, and two gaps let that happen:

1. **No in-flight guard on Run.** `handleRunAction` awaits `/server/control/checkLock`
   before anything marks the target as running, and the button stayed enabled. A second
   click (or a double-click) in that window launched again.
2. **Any lock counted as blocked, even the user's own Take Control.** The second launch
   saw the device locked and queued a one-shot copy instead of running. The host's
   scheduler requests its lock with no user id, so that job can never run under the
   user's Take Control: it retries every 20 s until the lock drops (heartbeat expiry or
   the idle monitor), which is the 10:49 start. On the customer's build a dequeued job's
   completion is also never recorded, so the row stays ⏳ even after it runs.

The second gap is wrong on its own, too: `/server/script/execute` already runs a script
under its own user's `manual_control` lock (same-user subordinate,
`lock_utils.acquire_lock`), so queueing it only ever produced a job that waited behind the
user.

## Fix

- `handleRunAction` is single-flight (ref + state); the Run button is disabled while a
  launch is in progress. One click, one launch.
- `splitDevicesByLockState(..., { allowOwnManualLock: true })` on the script path treats a
  `manual_control` lock whose `owner_user_id` is the current user (`useUserSession`, the
  same id Take Control and `/script/execute` use) as runnable, so the run goes straight to
  `/script/execute` and runs under that lock. The testcase path is unchanged: its server
  route has no same-user rule, so it still queues.

## Verification

- `tsc --noEmit` and `eslint src/pages/RunTests.tsx` clean.
- Not yet exercised in a browser or on the customer install. To confirm the original
  double launch there: two run requests within a second in the server log, and `QUEUED` /
  `WAIT LOCK RETRY` for the one-shot in the host's deployment log.
