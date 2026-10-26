---
id: BUG-0556
title: monitor-img / -audio / -subtitle ignore capture folders whose profile turns the service off (PC-host idle gate)
date: 2026-10-16
owner: mac:TASK-NN-profiles
status: fixed
---

## Question (owner, 2026-10-16)

"if we have a profile on vpt-monitor-img, [should it] ignore its capture folder so we should still save cpu and ram?"

## Answer

Yes, and it does today. The saving comes in three coordinated layers, all of which consult
**the same function** — `folders_needing_service(service, capture_folders)` in
`shared/src.lib.utils.monitor_profile`. The function is the single source of truth for
"does this device need this monitor service?", and a profile change can never leave the imager,
the audio unit and the host orchestrator in disagreement.

| layer | where | what it does when the device profile turns the service off |
|---|---|---|
| unit startup | `shared/src.lib.utils.monitor_service.wait_until_needed` (called at the top of `capture_monitor.py`, `transcript_accumulator.py`, `subtitle_monitor.py` *before* the heavy imports) | the unit loops every 60 s, holding only the python interpreter, until a device needs the service |
| host orchestrator | `apply_monitor_profiles` -> `_desired_state` -> `folders_needing_service_for_devices` | computes the per-unit restart mask; never restarts a unit the imager would have skipped, and vice versa |
| in-imager per-capture filter | `capture_monitor.py:_init_capture_dirs` (around line 1176) | drops capture folders whose device profile turns img off: no inotify watch, no per-capture frame worker, no per-capture incident worker |

## Evidence on vpt-lenovo1 (the test host)

vpt-lenovo1 has six HLS capture dirs, with `MONITOR_PROFILE=pc` as the box default and explicit
`DEVICE<N>_MONITOR_PROFILE` overrides on devices 2/3/4. The imager's most recent startup log:

```
[INFO] [capture5] profile does not use the img service, skipped
[INFO] [capture6] profile does not use the img service, skipped
[INFO] [capture1] profile does not use the img service, skipped
[INFO] Found 3 capture directories
[INFO] Monitoring [HOT (RAM)]: /var/www/html/stream/capture4/hot/captures -> capture4
[INFO] Monitoring [HOT (RAM)]: /var/www/html/stream/capture3/hot/captures -> capture3
[INFO] Monitoring [HOT (RAM)]: /var/www/html/stream/capture2/hot/captures -> capture2
```

3 of 6 capture dirs do nothing inside the imager. capture1, 5, 6 are the `pc` / `tv_lite` slots;
capture2, 3, 4 are `tv_app` / `egg_quality` / `counting_cars` and get the worker.

## Net effect, by host shape

| every device's profile is | imager process | imager per-capture work |
|---|---|---|
| `pc` / `tv_lite` (img: false) | a few MB, idle loop, no OpenCV, no inotify watches | none — service idles |
| mixed (some img: true, some false) | normal imager (~80-120 MB), full imports | runs only for the img: true capture folders; the rest are filtered |
| every device's profile is `tv_app` / `counting_cars` / `egg_quality` / `drone` (img: true) | normal imager | runs for every capture folder |

## What this turn changed

- The mechanism was already present. The change in this turn is **comments and docs** so the
  three call sites are discoverable from the code and from the operator-facing doc.
- `shared/src.lib.utils.monitor_service` — module docstring rewritten to explain the three
  coordinated layers and the single source of truth.
- `backend_host/scripts/capture_monitor.py`, `transcript_accumulator.py`, `subtitle_monitor.py`
  — top-of-`__main__` comment block annotated with BUG-0556, pointing to the gate.
- `shared/src.lib.utils.monitor_profile.folders_needing_service` — docstring names all three
  callers and the test that exercises the contract.
- `backend_host/src/lib/utils/monitor_profile._desired_state`, `services_to_restart` — comments
  cross-referencing the three call sites.
- `backend_host/scripts/monitor/core.py:1176` — the per-capture filter now references BUG-0556
  in the comment.
- `docs/agent/devices/MONITOR_PROFILES.md` — new section **§2a "The PC-host idle gate (BUG-0556)"**
  with the table above.
- `tests/backend_host/test_monitor_idle_when_not_needed.py` — new test verifying
  `wait_until_needed` returns the (empty) folder list immediately when there are no capture
  folders at all (boot-time state of a fresh host) and loops while a profile-less capture folder
  is present.

## Risk

None measurable. The mechanism is a refactor of the existing `wait_until_needed` /
`folders_needing_service` / `apply_monitor_profiles` trio; no public API changes, no DB schema,
no new dependency. The new comments are pure documentation; the new test is additive.

## Verification

- `python -c "import ast; ast.parse(...)"` for every edited Python file (in the commit).
- `pytest tests/backend_host/test_monitor_services_follow_profiles.py tests/backend_host/test_monitor_idle_when_not_needed.py`
  (in the commit).
- On vpt-lenovo1: `journalctl -u vpt-monitor-img --since "-1 min"` shows the per-capture filter
  applied; the test is in the live box and the next deploy picks up the new docstrings.
