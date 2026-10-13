# BUG-0425 — BLE remote panel reported a pairing timeout while the STB was still pairing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0425                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / ble-remote                                        |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Re-pairing a customer STB (Commscope, USB Belkin dongle) from the BLE remote panel: the panel showed
"STB did not complete handshake within 60 seconds" and the operator retried, yet the STB finished
pairing 45–60 s after the panel gave up. One of two re-pairs on 2026-10-05 looked failed for this
reason only.

## Root cause

The panel's pair loop (`useBluetoothRemote.ts`), its safety timeout and countdown
(`BluetoothRemote.tsx`) all stopped at 60 s. `start.sh` takes ~15 s to bring the adapter up, and the
STB in "Add new remote" mode can take up to ~2 min to find and pair the remote. The radio keeps
waiting after the panel stops; only the panel's verdict was wrong.

## Fix

One constant, `BLE_PAIR_WAIT_S = 120` in `frontend/src/hooks/controller/useBluetoothRemote.ts`, drives
the pair loop, the safety timeout, the countdown and the messages.

## Verification

Start Pairing on a BLE device: the countdown starts at 120 s and the panel reports success when the
STB pairs at any point within it.
