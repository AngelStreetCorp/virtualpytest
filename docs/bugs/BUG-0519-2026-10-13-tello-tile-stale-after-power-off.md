# BUG-0519 — Tello tile stuck on "Starting video…" with a green dot after the drone was switched off

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0519                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend host / Tello remote / frontend (Device tile)         |
| Fixed in  | build 90145 |
| Commit    | `worktree-agent-a54a03ff39f7072c0`                           |

---

## Symptom

Tile "Tello-C5B142 - vpt-pi4" showed the drone icon, "Starting video…" and a green status dot while the drone was off (no TELLO-* Wi-Fi in range, wlan0 back on the home Wi-Fi). No Scan chip, so the drone could not be paired again. Other observations the same day: "Checking… / Scanning" only, or the last battery/temperature (68 % / 96 degC) next to "Starting video…".

## Root cause

- `frontend/src/hooks/rec/useDroneWifiStatus.ts` (poll, `if ((status?.linked || status?.associated) && ownDrone && !manual)`) treated `linked` as "the drone is there". `linked` comes from `TelloRemoteController.get_status` (`backend_host/src/controllers/remote/tello.py`, `'linked': self.client is not None`): it only says the UDP socket object exists, and nothing ever clears it when the drone goes silent (a landed drone is not released; `_ensure_client` only re-enters SDK mode on the next command). So every 20 s poll and every 5 s quiet check kept the state `connected`, with `videoLive` false = "Starting video…", the connected state = green dot, no Scan chip (`state !== 'connected'`), and the old `telemetry` stayed in the badge.
- `tello_status` (`backend_host/src/routes/host_drone_routes.py`) computed `associated` (Wi-Fi on the drone) but never combined it with the freshness of the state datagrams (`state_age_s`).

## Fix

- Controller: `link_alive()` (airborne, or state datagram younger than `LINK_DEAD_S` = 10 s) is in `get_status`; `drop_dead_link()` releases the socket of a landed, silent drone (never airborne, non-blocking lock).
- Host route `tello_status`: new `connected` = host Wi-Fi on the drone's SSID AND `link_alive`. Not connected and not airborne: telemetry is blanked; off the drone's Wi-Fi the dead socket is dropped (`linked` false, `last_error` set). On the drone's Wi-Fi but silent the existing background relink re-enters SDK mode.
- Frontend hook: `statusIsConnected()` uses only `connected`. The quiet 5 s check drops a connected tile to `ap-not-found` (paused, so the Scan chip shows, grey dot, no battery badge) after `LINK_LOST_CHECKS` = 2 consecutive "not connected" answers; the 20 s poll goes straight to scan. No new polling. Scan works from that state.
- Unchanged: 85 degC takeoff gate, guard, land always allowed, airborne handling.

Tests: `tests/backend_host/test_tello_pair_routes.py::test_status_*` (wifi left, silent on AP, fresh, airborne), `tests/drone/test_tello_controller.py::test_silent_landed_drone_is_not_alive_and_its_link_is_dropped`, `::test_airborne_drone_link_is_never_dropped`, `node frontend/scripts/drone-link-check.mjs` (no frontend test runner exists).
