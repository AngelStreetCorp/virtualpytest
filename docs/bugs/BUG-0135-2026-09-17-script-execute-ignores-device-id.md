# BUG-0135 — The script API accepted a device id and ran the script on a different device

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0135                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | Medium (no data loss; a run silently executes against the wrong hardware and its result is recorded as if it were the requested device) |
| Area      | `backend_server/src/routes/server_script_routes.py`                         |
| Fixed in  | Unreleased                                                                  |
| Commit    | `33e9a03067` |

---

## Symptom

`POST /server/script/execute` takes `device_id` in its body. Sending a valid one does not put
the script on that device.

```
POST /server/script/execute
{"host_name":"host-clone-1","device_id":"device2",
 "script_name":"goto.py",
 "parameters":"--userinterface youtube-android-mobile --node video_player"}
```

`device2` on `host-clone-1` is a paired phone (`samsung SM-G998B`, model `phone_agent`). The run
executed against `host`, the VM's own VNC desktop, and drove an Android navigation tree through
Chromium:

```
🏗️ [goto] Creating host instance with device: device1...
[@controller_manager] Creating ONLY devices: ['device1']
[@controller_manager] Host created with 0 devices
⚠️  [goto] No 'device1' device found, falling back to host device...
🔍 [goto] Selecting device: host
[@db:execution_results:record_node_execution] node:home | host-clone-1:host_vnc | ✗ 1ms
```

The request was accepted, the device lock was taken on `host-clone-1:device2`, and the failure
was recorded — so from the API and from Test Reports the run looks like a `device2` run that
failed a verification. The log is the only place that says otherwise, and its report landed under
`script-logs/host_vnc/` rather than `script-logs/phone_agent/`.

## Root cause

`device_id` and the script's device selection are two unconnected paths.

The route puts `device_id` in the host payload, where it drives the device lock, the adhoc
execution row and the report path. But the script process does not read that payload. It builds
its devices from the host `.env` filtered by its own `--device` argument, which
`ScriptExecutor.create_argument_parser` declares with a default of `device1`:

```python
parser.add_argument('--device', help=f'Specific device to use (default: {self.default_device})')
```

Nothing appended `--device` to argv. So a caller who did not hand-write the flag into
`parameters` got `device1` regardless of what they asked for. On a host that has no `device1`
the script then falls back to the host's own VNC device rather than failing, which turns a
wrong-device run into a plausible-looking verification failure.

The scheduler path never had the problem — `deployment_scheduler` builds its parameter string
itself and appends `--device {dep['device_id']}`. Only the direct API caller was affected, which
is why this survived: the UI and the scheduler both go through paths that spell the flag out.

The same shape of fault made it hard to spot. `goto.py`'s docstring documented a positional
userinterface argument that does not exist (`goto.py example_androidtv --node live_fullscreen`),
while `_script_args` declares only flags. A bare positional is silently ignored and
`--userinterface` keeps its `example_mobile` default, so a call written from the docstring fails
with `User interface 'example_mobile' not found` and gives no hint that the argument was dropped.
Fixed in the same change; the same stale usage line is in `goto_live.py`, `device_get_info.py`
and `web/youtube_video_check.py`.

## Fix

`server_script_routes.execute_script` appends `--device <device_id>` to the parameter string
unless the caller already supplied the flag, mirroring what the scheduler does:

```python
if device_id and '--device' not in (parameters_normalized or ''):
    parameters_normalized = (f"{parameters_normalized} --device {device_id}"
                             if parameters_normalized else f"--device {device_id}")
```

An explicit `--device` in `parameters` still wins, so nothing that works today changes.

`test_scripts/goto.py` and `test_scripts/goto.md` drop the phantom positional and state that
every argument is a flag; `goto.md` also gains the `--variant`, `--verify` and `--device` rows it
was missing.

## Verification

Against the deployed server, the same request that produced `host_vnc` above must land on the
phone — `Creating host instance with device: device2` and a report under
`script-logs/phone_agent/`.

Not yet verified live: the fix is committed but not deployed, so the behaviour above still
reproduces on the running server until `update_core.sh` ships it.
