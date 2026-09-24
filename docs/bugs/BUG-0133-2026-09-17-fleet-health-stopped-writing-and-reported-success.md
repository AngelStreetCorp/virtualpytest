# BUG-0133 — The daily fleet-health table stopped writing nine days ago and reported success every morning

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0133                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed                                                                       |
| Severity  | Medium (no data loss, but the fleet-health history has a nine-day hole and every health signal said the job was fine) |
| Area      | `scripts/fleet_health_report.py`                                            |
| Fixed in  | Unreleased                                                                  |
| Commit    | `ccd610d20a`                                                                |

---

## Symptom

`fleet_health` had 416 rows and its newest was `2026-09-08`, nine days old, while
`vpt-fleet-health.timer` was enabled, active, and had last run 1 h 27 min earlier.

Nothing anyone would normally look at showed a problem:

```
$ systemctl list-timers 'vpt-fleet*'
NEXT                         LEFT     LAST                         PASSED       UNIT
Fri 2026-09-18 07:01:34 CEST 22h left Thu 2026-09-17 07:00:44 CEST 1h 27min ago vpt-fleet-health.timer
```

The service ran to completion every morning, wrote its markdown report, uploaded it to MinIO
and exited 0. The `vpt-fleet-health` Grafana dashboard, which reads the table rather than the
report, had simply been showing nine-day-old data.

Found while building Monitoring → Analytics (TASK-20): `fleet_health.verdict` looked like the
obvious source for "how many devices are up", and the data was too old to use.

## Root cause

Two independent faults, and the second is what made the first survive nine days.

**1. The write used the anon key, which had been revoked.**
`db_insert_rows()` posted to `/rest/v1/fleet_health` with `SUPABASE_ANON_KEY`. Its docstring
explained the choice: *"present on the server VM; RLS policy is public"*. That was true when it
was written. The service_role lockdown (TASK-10) closed anon, and the table went quiet the
same day. Every run since logged exactly one line:

```
WARNING: DB insert: FAILED (HTTP Error 401: Unauthorized)
```

**2. A failed write returned 0.** The call site printed a `WARNING:` prefix and fell through to
`return 0`, so systemd recorded a clean run every morning. A job that fails silently and
reports success is indistinguishable from a healthy one until somebody queries the table by
hand — which is what finally happened, nine days later and for an unrelated reason.

## Fix

`scripts/fleet_health_report.py`:

- Write with `SUPABASE_SERVICE_ROLE_KEY`, falling back to `SUPABASE_ANON_KEY` for an install
  that has not been locked down.
- A failed insert prints to stderr and **exits 1**, so systemd marks the unit failed. The
  report is written and uploaded before this point, so failing here costs nothing except the
  visibility it should have had from the start.

## Verification

Both credentials, against the live database, through the real function:

```
anon key (the old behaviour) -> FAILED (HTTP Error 401: Unauthorized)
service_role (the fix)       -> OK (1 rows, HTTP 201)
```

The 401 reproduces the exact error the service had been logging. The test row was deleted
afterwards.

Then the fixed script was deployed to the server and the unit run once by hand:

```
Sep 17 08:32:05 vpt-fleet-health: Fleet: OK=5 IDLE=4 DEGRADED=3 DOWN=0 UNKNOWN=0
Sep 17 08:32:06 vpt-fleet-health: DB insert: OK (12 rows, HTTP 201)
```

`fleet_health` is now 428 rows with `max(generated_at) = 2026-09-17`. The nine-day gap
(2026-09-09 to 2026-09-16) cannot be backfilled — the daily snapshot is computed from live
state that no longer exists — so that hole is permanent in the history.

## Aftermath

The same shape is worth looking for elsewhere: any scheduled job whose failure path prints a
warning and returns 0 will report success forever. This one was only caught because someone
needed the table for something else.
