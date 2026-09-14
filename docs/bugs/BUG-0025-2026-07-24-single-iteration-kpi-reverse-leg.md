# BUG-0025 — Single-iteration KPI runs walk the device all the way back

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0025                                                     |
| Reported  | 2026-07-24                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | kpi / navigation / test_scripts                             |
| Fixed in  | build 8713                                                   |
| Commit    | `a3705d03c` (+ `6da070d3b`)                                 |

---

## Symptom

A KPI run with `--iterations 1` navigated **forward** (the leg being measured) and then **walked
the device all the way back** to the source node — roughly doubling the run time while measuring
nothing on the return. A run whose forward leg **failed** also still ran the full reverse walk.

## Root cause

The reverse leg exists only to **reposition** the device at the source node so the *next*
iteration's forward navigation can start from a known place. With a single iteration there is no
next iteration, so the reverse leg is pure wasted navigation. The earlier behaviour also continued
into the reverse even after a failed first iteration.

## Fix

`test_scripts/kpi_measurement.py` (`6da070d3b`, then `a3705d03c`):

- Skip the reverse leg **entirely** when the run has a single iteration — whether the forward leg
  passed or failed. A 1-iteration run measures only the selected direction and stops.
- A failed first iteration stops instead of running the reverse.

Multi-iteration runs are unchanged: they still reverse between iterations to reposition for the next
forward leg.

## Verification

Run any KPI with `--iterations 1`: it performs the forward (measured) navigation and stops — no
walk-back — for both a passing and a failing forward leg. Run with `--iterations 2+`: the reverse
leg still runs between iterations.
