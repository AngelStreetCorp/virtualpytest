# BUG-0419 — The web/VNC host device could not get a preferred userinterface, so no Localize button

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0419                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend_host / controller_manager |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the Device page of a web host (device `host`, e.g. host-clone-1) the stream header had no Localize button, and there was no way to give it a preferred userinterface.

## Root cause

`preferred_userinterface` / `preferred_variant` were read from `DEVICE{N}_USERINTERFACE` / `DEVICE{N}_VARIANT` for numbered devices only. The built-in `host` VNC device never got them, and the Device page shows the button only when the device has a preferred userinterface.

## Fix

The `host` device reads `HOST_USERINTERFACE` and `HOST_VARIANT` from the host `.env`, the same way the numbered devices do. Unset means unchanged behaviour.

## Verification

- After deploy and `HOST_USERINTERFACE=<name>` in the host `.env` (then restart `vpt-host`): the host device in `getAllHosts` carries `preferred_userinterface`, and the Device page shows the Localize button in Live mode.
