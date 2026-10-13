# BUG-0222 — A standby wake after a long dwell was never measured: the cold-wake woke the STB before the timed POWER press

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0222                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | High — every standby run with a dwell of 5 min or more failed with no KPI, on any standby mode |
| Status    | Fixed (pending deploy)                                            |
| Area      | `test_scripts/tv/standby_measurement.py`                          |
| Fixed in  | Unreleased                                                        |
| Related   | [BUG-0204](BUG-0204-2026-10-01-standby-wake-already-awake-blamed-kpi.md) (made this failure visible instead of blaming the KPI reference) |
| Commit    | this commit                                                       |

---

## Symptom

Customer, `standby_measurement`, variant `base_5.30`, mode `[TC267] Active Start
(Lukewarm)`, edge `home → standby`, dwell 6 min, 1 iteration:

```
🌅 Deep standby (≥5min) — WoBLE cold-wake before POWER
⚠️  cold_wake NOT HID-ready (POWER may be dropped) after 30.0s
☀️  WAKE — goto 'home' (measured standby → live)
❌ Stale position verification failed - clearing position (was: standby)
✅ Already at target 'home' - no navigation needed
❌ Wake edge 'standby → home' did not run in 1/1 iteration(s) …
```

The same happened on Eco (cold) standby earlier the same day.

## Cause

At a dwell of 5 min or more the script emits the BLE WoBLE cold-wake first, assuming it
only restores the BLE link, waits for the HID link, and then runs the wake edge so its
POWER press does the timed wake. On these STBs the cold-wake wakes the box all the way
to live on its own. The wake `goto(home)` then finds Home already on screen, takes no
edge, presses no POWER, and queues no KPI — so the one transition the run exists to time
was never measured. (Pressing POWER regardless would have put the box back to standby.)

## Fix

For a dwell of 5 min or more, the cold-wake **is** the wake and is what gets timed:

- No POWER press. The script sends the cold-wake, notes the emission time, then polls
  the live node's own verifications (up to 60 s, `COLD_WAKE_LIVE_TIMEOUT_S`).
- When live appears, it records the same `standby → live` execution row a POWER wake
  produces (the variant graph's wake edge, through the executor's own
  `_record_step_execution_results`) and queues the KPI through `_write_kpi_request_file`
  with **start = cold-wake emission** and end anchor = live verified. vpt-kpi.service
  scans back for the first frame the live node appears, so the KPI is "BLE wake signal
  → live on screen", on the same row, action set and report as before.
- The executor's position is set to the live node so the next iteration's
  `goto(standby)` plans from the right place.
- With a non-BLE remote, or if live does not appear within 60 s, it falls back to the
  wake edge (POWER), handled as before (BUG-0204 reports it if the box was already up).

The wait-for-HID-ready step before POWER is gone: nothing presses POWER on the
cold-wake path any more.

## Verification

- `python3 -m py_compile`.
- Offline, against a networkx graph shaped like the runtime's and stubbed
  remote / verifier / executor: the wake step resolves to the reverse edge and the wake
  action set; live verified on the 3rd poll → position updated, row recorded as success,
  KPI queued with `action_timestamp` = cold-wake time ≤ `verification_timestamp`, report
  step "Cold-wake from deep standby (WoBLE) → home". Live never seen → returns False,
  nothing recorded or queued (POWER fallback). Non-BLE remote → returns False.
- First customer run (host on build 8713, script updated alone): the cold-wake path ran
  and verified Home after 13.4 s, then stopped on
  `'NavigationExecutor' object has no attribute '_mark_position_verified'` — a helper
  added after 8713. The call was dropped (the next goto re-verifies the position when
  it needs to); every other executor call the path makes exists with the same
  signature in 8713.
