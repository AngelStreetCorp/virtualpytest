# BUG-0271 — The BLE remote woke a stale bond, and keys that reached no box were reported as sent

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0271                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — every key went nowhere while every step passed        |
| Area      | `backend_host/src/controllers/remote/bluetooth/hid_remote.py`, `backend_host/src/controllers/remote/bluetooth.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `d8d100372`, `5666223f7`                                     |

---

## Symptom

A set-top box driven by the emulated BLE remote stayed asleep: the wake-on-press directed advert
timed out, no key reached the box, and `press_key` still returned success, so testcase steps
passed while nothing happened on screen.

## Root cause

- The adapter held two bonds that both carried the HID CCC (the box had re-paired under a new
  identity without the old bond being removed). `_bonded_peer_mac` broke that tie by D-Bus order
  and returned the stale identity; `wake_on_press` aimed `ADV_DIRECT_IND` at it and gave up after
  `WAKE_TIMEOUT_S` without trying the other bond.
- `press_key` returned `True` as soon as the key name was written to the daemon's FIFO, whether or
  not a peer was connected to carry it.

## Fix

- The daemon records the last MAC that went `Connected=True` and persists it in its status file.
  Bonds are ranked by `_rank_bonds`: connected, then HID-ready, then last connected, then newest
  bond file, then D-Bus order. `wake_on_press` tries the best bond, then each other HID-ready bond,
  and publishes `waking` in the status file meanwhile.
- `press_key`: with a key-channel subscription it returns at once (one file read); otherwise it
  waits up to `WAKE_TIMEOUT_S` + 2 s (longer while the daemon is still waking) and fails with
  `no BLE peer connected after wake` if no peer connected.

## Verification

`tests/backend_host/test_ble_wake_target.py`, `tests/backend_host/test_ble_press_key_peer.py`.
Live: with the box in active standby, press a key; the daemon log shows the wake order and the
box reconnects. With the box unplugged, `press_key` fails with the new error after ~17 s.
