# BUG-0096 — Host registration crashed for any device without `DEVICEn_VIDEO_STREAM_PATH`

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0096                                                                    |
| Reported  | 2026-09-15                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (latent: every fleet `.env` sets the key, so it only bit the first new slot) |
| Area      | `backend_host/src/controllers/controller_manager.py::_get_devices_config_from_environment` |
| Fixed in  | build 9151                                                                                 |

---

## Symptom

First `phone_agent` slot added to `host-clone-1` (TASK-17 §1.1, without `DEVICE2_VIDEO_STREAM_PATH`):

```
❌ [HOST] Registration error: name 'host_name' is not defined
  File ".../controller_manager.py", line 177, in _get_devices_config_from_environment
    video_stream_path = f"/host/{host_name}/stream/device{i}"
NameError: name 'host_name' is not defined
```

`vpt-host` stays `active` but never registers, so the server shows the host with its old
device list and every new device is invisible.

## Root cause

The "auto-construct the stream path from HOST_NAME" fallback referenced a local `host_name`
that only exists in `create_host_from_environment`, not in this function. Nobody hit it because
every `.env` in the fleet sets `DEVICEn_VIDEO_STREAM_PATH` explicitly. The fallback value was
also wrong for the fleet convention: hosts use `/host/stream/<capture folder>` (the frontend
prefixes the host URL), not `/host/<name>/stream/deviceN`.

## Fix

`5ca3ed075d..` on `feat/mobile-app`: the fallback derives the stream path from the capture folder
basename (`/var/www/html/stream/capture2` → `/host/stream/capture2`), which is exactly what every
explicit `.env` spells. The slot docs (`docs/technical/MOBILE_APP.md`, `.env.example`, TASK-17
§1.1) now list the explicit key too, matching the rest of the fleet.

## Verification

- `tests/backend_host/test_device_env_config.py` — a device with a capture path and no stream
  path yields the derived path; an explicit path wins.
- host-clone-1 registered `device2 (phone_agent)` after the fix was deployed (see TASK-17 log).
