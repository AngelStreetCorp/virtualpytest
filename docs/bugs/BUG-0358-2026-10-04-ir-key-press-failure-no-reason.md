# BUG-0358 — A failed IR key press showed "no error details from controller"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0358                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed                                                        |
| Severity  | Low - the report hid why a key press failed                  |
| Area      | `backend_host/src/controllers/remote/infrared.py`            |
| Fixed in  | build 90145 |
| Commit    | `065b8ae9df`                                                 |

---

## Symptom

A replay on stb3 (vpt-pi1) failed at `live → live_chup`: "press_key: Action 'press_key' failed (no error details
from controller) [key='CHANNEL_UP']". The controller's own prints were not in the execution log either.

## Root cause

`InfraredRemoteController.execute_command` returned only `{'success': False}`. The reason was in
`_last_send_error` (used by the Take Control status dot) and never in the response. The kernel log had it:
the IR Toy wedged at that second (`ir_toy 1-1.2:1.1: fail to submit tx buf urb: -16`, then `-110`), the firmware
wedge described in `docs/agent/devices/INFRARED.md` §6.1.

## Fix

A failed `press_key` returns `error` with the send failure (ir-ctl stderr, timeout, not connected, key not in the
keymap; the last two now also turn the status dot red). An unknown command says so.

## Verification

Deployed to vpt-pi1 2026-10-04. The IR Toy recovered by itself: three `ir-ctl --send` test pulses exited 0 with no
new transmit error (`fail to submit tx buf urb`); the receive side still logs `unexpected response` bursts, and the next stb3 explore and replay sent every key.
