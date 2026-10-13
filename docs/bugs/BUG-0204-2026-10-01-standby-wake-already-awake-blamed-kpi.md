# BUG-0204 — Standby measurement blamed a missing KPI reference when the STB had already woken during the cold-wake

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0204                                                          |
| Reported  | 2026-10-01                                                        |
| Severity  | Medium — the run fails with a wrong diagnosis, sending the user to edit KPI settings that were already correct |
| Status    | Fixed (pending deploy)                                            |
| Area      | `test_scripts/tv/standby_measurement.py`                          |
| Fixed in  | Unreleased                                                        |
| Commit    | this commit                                                       |

---

## Symptom

`standby_measurement` on a variant with a `home ↔ standby` edge, standby mode
`standby_active`, dwell 6 min. Every action passed, then the run failed with:

```
No KPI measurements recorded for 'standby → home'. The wake edge likely has no KPI
reference — add kpi_references to the 'standby → home' action set, or give the 'home'
node a verification (with use_verifications_for_kpi=true).
```

The variant's `standby → home` action set did have KPI configured.

## Cause

The step report shows the real sequence:

| Step | Result |
|---|---|
| `home → standby` | POWER, black screen verified |
| Wait in standby 6 min | dwell |
| Cold-wake from deep standby (WoBLE) | FAIL — HID link not ready within 30 s |
| `home → home` | **Already at Destination** — no navigation |

A dwell of 5 min or more triggers the WoBLE cold-wake first, on the assumption that it
only restores the BLE link and the wake edge's POWER press does the measured wake. On
this STB the cold-wake woke the box all the way to Home. The wake `goto(home)` then
verified it was already there and returned `already_at_target`, so the
`standby → home` edge never ran and no KPI was queued. The script treated that as a
successful wake and, finding no KPI row, fell through to the "no KPI reference" message.

## Fix

- A wake whose `goto` returns `already_at_target` is counted as **not traversed**, not as
  a success, and logged as such per iteration.
- The DB poll only waits for KPI rows from wakes that actually ran (no 60 s wait for rows
  that can't exist).
- The error names the real cause: the wake edge did not run in N iterations because the
  device was already at the live node, and — when the cold-wake ran — that the STB woke
  during it, before the measured POWER press.

Also in this change: the wake action set id used to filter KPI rows is read from the
run's variant-resolved navigation graph (the graph `goto` traverses and whose id the
executor stamps on the KPI row) instead of the raw base DB row. A variant whose
`action_sets` override carries different ids than base would otherwise have had every
measured row filtered out.

## Not fixed here

The run still produces no number for long dwells on an STB that wakes on WoBLE alone.
Measuring the cold-wake itself as the wake transition is a separate change.

## Verification

- `python3 -m py_compile test_scripts/tv/standby_measurement.py`.
- `_resolve_action_set_id` exercised offline against a networkx graph shaped like
  `create_networkx_graph`'s output (forward edge `[fwd, rev]`, reverse edge `[rev]`):
  `standby → home` → reverse id, `home → standby` → forward id, missing pair → `''`.
- Not yet re-run on the device.
