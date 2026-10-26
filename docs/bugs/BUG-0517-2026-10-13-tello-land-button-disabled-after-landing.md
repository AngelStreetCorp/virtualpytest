# BUG-0517 — Tello: Take off stayed unavailable after landing, and Land answered "error" on the floor

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0517                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend host / Tello remote / frontend                       |
| Fixed in  | build 90145 |
| Commit    | `fix/tello-land-button`                                      |

---

## Symptom

Tello TELLO-C5B142 (vpt-pi4): after "Take off: ok" and a landing the drone read H 0.0 m, HS 0.0 m/s, but the main button stayed on "Land" / greyed instead of "Take off", and clicking it showed the red line "Land: error". Take off could not be sent again without re-opening the remote.

## Root cause

`TelloRemoteController._send_guarded` (`backend_host/src/controllers/remote/tello.py`) only cleared `airborne`, the guard pose and the keepalive when the Tello answered `ok` to `land`. On the floor the Tello answers `error`, so the `error` return path left `airborne = True` and the guard's dead-reckoned `pose.z` at takeoff height. The 2-second `get_telemetry` poll then kept reporting `airborne: true` (TelloRemote.tsx `pollTelemetry`), `onMain` put the phase back to `flying` after the failed land, and the guard refused the next `takeoff` with "already flying" (`safety.py` `check`).

## Fix

- Controller: a `land` answered with `error` while the state stream reads the floor (`h` <= 10 cm, `GROUND_H_CM`) is a success (`already_grounded`, message "Already on the ground") and clears `airborne`, the guard pose and the keepalive. With the drone really in the air an `error` on land is still a failure. `land` stays always allowed; no ceiling, geofence, battery or 85 degC check changed.
- UI (`TelloRemote.tsx`): after a land attempt that fails with the height at the floor, the phase goes to `landed` (Take off comes back) and the line reads "Already on the ground"; the poll corrects every other case.

Tests: `tests/drone/test_tello_controller.py::test_land_on_the_ground_is_success_and_a_new_takeoff_is_accepted`, `::test_land_error_in_the_air_is_still_a_failure`.
