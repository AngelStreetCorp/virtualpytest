# BUG-0108 — No script can drive a paired phone: the remote controller only exists inside vpt-host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                      |
|-----------|----------------------------------------------------------------------------|
| ID        | BUG-0108                                                                   |
| Reported  | 2026-09-16 ("now how to run a test on the paired device?")                  |
| Status    | Fixed (pending deploy beyond host-clone-1)                                  |
| Severity  | High (the whole point of `features/mobile-app` phone-as-device)             |
| Area      | `features/mobile-app/backend_host` + controller registry                    |
| Fixed in  | build 9151                                                                  |
| Commit    | TBD                                                                        |

---

## Symptom

A paired phone drives fine from the Device Control remote panel, but **every script run
against it fails on its first action**:

```
[@controller_manager:_create_controller_instance] WARNING: Unknown controller remote_phone_agent
[@controller_manager:_create_device_with_controllers] ✓ Device device2 created with capabilities: ['av', 'verification']
[@lib:action_executor]    Error: Remote controller not available
❌ Navigation failed at step 1 (Entry → home): action failed - Actions failed: press_key: Remote controller not available
```

The device is there, the stream is there, verification controllers are there — `remote`
is simply absent, so nothing can be pressed, tapped or typed.

Two separate things had to be wrong for a phone test to be impossible, and both were:

1. **Nothing to navigate.** `phone_agent` has been in
   `shared/src/lib/config/device_capabilities.py` since TASK-17, but was never added to
   the `device_models` table. `UserInterface.tsx` builds its model dropdown from that
   table (`useDeviceModels`), so a navigation tree for a phone could not be created in
   the UI, and no userinterface listed `phone_agent`.
2. **Nothing to drive it with** — the controller described below.

TASK-17 §6 step 5 ("run a navigation script against the phone") was therefore never
reachable; the acceptance runs went through the remote panel, which runs *inside*
vpt-host and so never touched this path.

## Root cause

`PhoneBridge` owns the Socket.IO session to the phone, so it only exists in the
vpt-host process, and `features/mobile-app/backend_host/register(app)` — which puts
`phone_agent` into `controller_registry` — needs a Flask app.

Scripts do not run in that process. `ScriptExecutor._execute_script_subprocess`
launches every script as its own Python process, which builds its own `Host` through
`controller_manager.create_host_from_environment()`. There is no app there, so
`register(app)` never runs, the registry is empty, and
`_create_controller_instance('remote', 'phone_agent', …)` falls through to
`WARNING: Unknown controller`.

This is specific to a socket-backed device. An adb device does not care: the
subprocess builds its own `AndroidMobileRemoteController` and talks to adb directly.
A phone's only route to the device is a socket that belongs to another process.

## Fix

Give the subprocess a controller that calls back into vpt-host, where the socket is.

| File | Change |
|---|---|
| `features/mobile-app/backend_host/remote_bridge.py` (new) | `RemoteBridgeClient`: implements the only two methods `PhoneAgentRemoteController` asks of a bridge — `rpc()` (POST `/host/phone/rpc`) and `get_slot()` (GET `/host/phone/slots/<id>`). Frames stay a local file read: the subprocess runs on the same machine. |
| `features/mobile-app/backend_host/__init__.py` | new `POST /host/phone/rpc` route (runs one command on behalf of a caller outside this process, returning the bridge ack verbatim) + `register_controllers()`, the no-Flask registration path. It **bails out if the implementation is already registered**, so inside vpt-host the real in-process bridge is never replaced by an HTTP client pointed at itself — which would deadlock a host running a single gevent worker. |
| `features/mobile-app/backend_host/bridge.py` | `_Slot.summary()` now carries `frame_path`, the one field `RemoteBridgeClient` cannot derive. |
| `shared/src/lib/utils/features.py` | `register_feature_controllers(part)` — the no-Flask sibling of `register_feature_blueprints`, calling each enabled feature's optional `register_controllers()`. |
| `backend_host/src/controllers/controller_manager.py` | calls it at the top of `create_host_from_environment()`, so any feature-contributed controller also exists in a script subprocess. |
| `features/mobile-app/db/001_phone_agent_device_model.sql` (new) | the missing `device_models` row, for every team. Not added to core's `create_default_device_models()`: the defaults must not change when the optional feature is absent. |
| `features/mobile-app/backend_host/phone_sim.py` | `PhoneSim.__init__()` accepts `device_id`; `main()` passed it for the `--token` path and crashed with `TypeError` before the sim could connect. Only the `--qr` path worked. |

Content, not code, and therefore not migrated: a `phone_home` userinterface
(`entry-node → home ↔ settings`, `home ↔ recents`) was created as a starter tree for a
phone. `settings` verifies with OCR off the stream — `phone_agent` has no adb or appium
verification controller, but its AV side is the ordinary `hdmi_stream` capture folder,
so text verification works and needs no reference capture.

## Verification

On host-clone-1, with `features/mobile-app/backend_host/phone_sim.py` paired into slot
`device2`:

```
goto.py --userinterface phone_home --node recents --device device2
  → 2 steps, 6 screenshots, Result: SUCCESS

goto.py --userinterface phone_home --node settings --device device2
  → step 2 runs launch_app, then fails on the OCR check:
    "Text pattern 'Settings|…' not found (best score 0.000 < threshold 0.800)"
```

The second is the expected outcome against a simulator whose frame is a static test
image, and it is the useful half of the proof: the command reached the phone and the
verification ran. Before the fix both runs died at step 1 with
`Remote controller not available`.

Still to confirm on a real phone: that `launch_app com.android.settings` opens Settings
and the OCR check passes.
