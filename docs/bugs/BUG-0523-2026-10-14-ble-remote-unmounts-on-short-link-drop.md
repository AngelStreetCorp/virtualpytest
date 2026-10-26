# BUG-0523 — BLE remote unmounts on every short link drop

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0523                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-pi1 stb4 the Bluetooth remote "sometimes unmounts": the buttons disappear and the
panel shows "Waking STB…" for ~30 s, then the remote comes back.

## Root cause

vpt-pi1's onboard BCM4345 shares its radio with Wi-Fi; while video streams, the STB link
hits a supervision timeout (bluetoothd disconnect reason 1) roughly every few minutes. The
bond is intact and a key press re-establishes the link in ~2 s (`wake_on_press` on the
host), but the panel only rendered the buttons while `hid_ready` was true, so every drop
swapped to the action screen, and the auto-wake effect in `useBluetoothRemote` fired a WAKE
sentinel on every drop (its once-per-cycle flag resets on each reconnect).

## Fix

First attempt (60 s grace from the last healthy status) was not enough: on vpt-pi1 the link
often dies again ~20 s after reconnecting, before HID resolves, so the "last healthy" time went
stale, the auto-wake fired and the panel still swapped to "Waking STB…".

Now `frontend/src/hooks/controller/useBluetoothRemote.ts` sets `everHealthy` the first time the
link is fully healthy in the session; from then on, while the bond is present and the daemon is
up, any lost link or HID is `reconnecting` — no time limit. The auto-wake still runs in the
background. `BluetoothRemote.tsx` keeps the remote image mounted while `reconnecting`, with an
amber badge ("Reconnecting…", or "Waking STB…" while the auto-wake runs) and an amber dot. The
action screen only appears with no bond, the daemon down, pairing in progress, or after the
operator presses Power (cold wake).

## Verification

tsc + eslint clean; deployed bundle checked on the live page.
