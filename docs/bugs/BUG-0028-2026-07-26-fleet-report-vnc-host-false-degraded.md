# BUG-0028 — Fleet health report flags idle VNC hosts as DEGRADED (freeze / audio loss)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0028                                                     |
| Reported  | 2026-07-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (report noise, no functional impact)                     |
| Area      | scripts / fleet health report (GOAL-04)                      |
| Fixed in  | build 8713                                                   |
| Commit    | `fda35f908`                                              |

---

## Symptom

The daily fleet health report marked healthy `host_vnc` devices as **DEGRADED**:

- `host-clone-1` — *"freeze DURING ACTIVITY — static picture while device is in use"*
  while `ookla_speedtest` was running on it.
- `host-clone-3` — *"audio loss ongoing (confirmed by current frame)"*.

Both hosts were fine. The AI diagnosis then compounded it, recommending a capture-software
restart for a non-existent freeze.

## Root cause

`scripts/fleet_health_report.py::assess_device` applied AV-device semantics to every model:

1. **Freeze during activity = fault** — correct for an STB playing video, wrong for a PC
   desktop captured over VNC: a running script (speedtest, ADB automation) doesn't animate
   the desktop, so a static picture during "activity" is the normal state.
2. **`audio_loss` incident + current frame `audio: false` = fault** — `host_vnc` captures
   have no audio path at all, so "audio loss" is permanently true and meaningless.

## Fix

`scripts/fleet_health_report.py` — model-aware assessment via a new `DESKTOP_MODELS`
set (`{"host_vnc"}`):

- Freeze on a desktop model returns **OK** — *"static desktop picture — normal for a
  VNC/PC host, even during activity (not a fault)"* — regardless of activity.
- `audio_loss` incidents are ignored for desktop models.
- The `--ai` diagnosis prompt gains the domain rule so the AI never blames freeze/audio
  on `host_vnc` devices.

Blackscreen and capture-freshness checks are unchanged for all models (a black or stalled
VNC frame still indicates a real capture problem).

## Verification

Direct calls to `assess_device` with the two reported scenarios:

- `host_vnc` + open freeze incident + running deployment → `OK` (was DEGRADED).
- `host_vnc` + open audio_loss + current frame `audio: false` → `OK`, "capture fresh" (was DEGRADED).
- Control: STB model + freeze during activity → still `DEGRADED` with the freeze reason.
