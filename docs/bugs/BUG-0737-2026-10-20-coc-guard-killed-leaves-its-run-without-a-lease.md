# BUG-0737 — The CoC guard was killed by the box and its run carried on without a lease

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0737                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | game / clash of clans (TASK-100)                             |
| Fixed in  | build 90145 |
| Commit    | see the merge commit                                          |

---

## Symptom

At 19:03:00 UTC on 2026-10-20 the guard of the CoC hourly run died while the run was still on the
phone:

```
2026-10-20T18:59:07Z claimed 966710c2 on node1-vpt/vpt-pi1/device1 (ttl 10 min, priority P3,
                  renewed every 3 min), guarding the run of 19:00 UTC
2026-10-20T19:02:40Z the run of 19:00 UTC is still on the phone (running)
2026-10-20T19:03:00Z released 966710c2
```

The systemd journal says why the process ended - and it was not the guard's own doing:

```
Oct 20 19:03:00 codebox systemd[494]: coc-run-lease.service: Main process exited, code=exited, status=143/n-a
```

`status=143` is SIGTERM. systemd did not stop the unit (there is no "Stopping" line), the lease
registry did not take the lease away (no `E_YIELD_REQUIRED`, no waiter), and the run did not end
(the ledger had no settle row). Something on the codebox sent the guard SIGTERM from outside.

The guard released the lease on its way out - that is what its `finally` block does - and from
19:03 on, **the CoC run was on the phone with nobody holding the lease**: another agent could take
`vpt-pi1/device1` and drive the same phone at the same time. The run itself carried on (it was
never asked to stop), so nothing looked broken; the protection was simply gone.

## Root cause

Two gaps, one behind the other.

1. **A killed guard does not come back.** The unit ran the guard once (`Type=oneshot`) and nothing
   restarted it. A guard that is killed - by the box's health watchdog, by a session reset, by
   anything outside systemd - leaves the rest of its run unguarded.
2. **A guard that comes back mid-hour would have held the phone far too long.** The guard decides
   which run it belongs to from the clock: a claim that lands within ten minutes after the top of
   the hour belongs to that hour, everything else belongs to the **next** one (`guarded_hour()`).
   A guard restarted at 19:07 therefore belongs to the trigger of 20:00, and it would have kept
   the phone until 20:02 - long after the run it was watching was over - which is exactly what the
   owner rule forbids ("hold a device lease only while you actively control it").

## Fix

* **The unit restarts a failed guard** (`~/.config/systemd/user/coc-run-lease.service`, local
  only - the integration lane refuses any diff that touches a systemd unit):

  ```ini
  # A guard that is killed from outside (SIGTERM: the box's health watchdog, a session reset) must
  # come back: the run it watches is still on the phone and nobody else holds the lease. Only a
  # failed unit is restarted - the clean ways out (the run ended, the run yielded) are a success.
  Restart=on-failure
  RestartSec=20
  ```

  `SuccessExitStatus=6` (the run yielded the phone to somebody who was waiting) stays a success,
  so a normal hour is not restarted.

* **The run's own ledger now ends the wait.** The ledger on the phone records a `settle` when the
  run is really over, and it is the fast signal (the platform's own history lags by minutes). The
  guard reads it on every poll - not only while it is yielding - so a guard that belongs to the
  next trigger still gives the phone back as soon as the run it watches is over:

  ```python
  led = ops.ledger_since(since_ts)
  if led.get("settled") and (not led.get("reserved") or led["settled"] == led["reserved"]):
      finished = True
      log(f"the run stopped on the phone (stop={led.get('stop')}), the lease goes back now")
      break
  ```

  The run id matters: a run of 60 min that starts at 19:00 ends at 20:00, after the guard of
  20:00 has started. Its settle row belongs to that older run, so it must not free the phone
  while the run of 20:00 is on it - the ledger's last reserve says which run is the current one.

## Tests

`tests/scripts/test_coc_run_lease.py` (40 tests):

* `test_a_guard_started_in_the_middle_of_the_hour_gives_the_phone_back_when_its_run_is_over` - a
  guard that starts at 11:34 (so it belongs to the trigger of 12:00) must give the phone back
  within two minutes of the run's settle row, not at the next trigger. Without the fix the test
  fails: the guard holds the phone for two hours.
* `test_a_run_that_ended_late_does_not_free_the_phone_of_the_run_that_is_on_it` - the settle row
  of the previous run (a run of 60 min ends at 20:00, after the guard of 20:00 started) must not
  free the phone while the run of 20:00 is on it. Without the fix the guard lets the phone go at
  that settle row.

## Verification

* The new test fails on the code without the fix (`the phone must go back as soon as the run is
  really over`) and passes with it.
* The unit change is live: `systemctl --user show coc-run-lease.service -p Restart` answers
  `Restart=on-failure`, `RestartUSec=20s`.
* The guard of the run of 19:00 was restarted by hand at 19:06:58 (`claimed 32e941ab ... guarding
  the run of 19:00 UTC`) and carried that run to its end.
