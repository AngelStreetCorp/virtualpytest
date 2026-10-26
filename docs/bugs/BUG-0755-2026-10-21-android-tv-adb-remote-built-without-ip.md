# BUG-0755 — Android TV / Fire TV got a dead adb remote next to IRTrans, and ignored the power API

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0755                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A Fire TV configured with `DEVICE<N>_MODEL=android_tv` and only an IRTrans remote
(`DEVICE<N>_IR_TYPE=fire_tv`, `DEVICE<N>_IR_IP`, `DEVICE<N>_IR_LED`) showed two remotes in
Take Control: the IRTrans one and an Android TV adb remote that could not reach anything.
The `DEVICE<N>_POWER_NAME` / `POWER_API_URL` / `POWER_API_KEY` lines on the same device
were silently ignored: no power controller was built.

## Root cause

- `create_controller_configs_from_device_info()` in
  `backend_host/src/controllers/controller_config_factory.py` built every remote listed
  for the model. The external remotes (IR, IRToy, IRTrans, BLE) are skipped when not
  configured, but the adb remote was always built, with `device_ip` falling back to
  `192.168.1.100`. Its adb verification controller was built too.
- `DEVICE_CONTROLLER_MAP` in `shared/src/lib/config/device_capabilities.py` listed only
  `tapo` and `wol` as power for `android_tv` and `fire_tv_fireos`; `api_power` was `stb` only.

## Fix

- The adb remotes (`android_mobile`, `android_tv`, `vega`) are built only when
  `DEVICE<N>_IP` or `DEVICE<N>_ADB_SERIAL` is set; when skipped, their adb verification is
  skipped as well.
- `android_tv` and `fire_tv_fireos` accept `api_power` (still built only when
  `POWER_NAME`, `POWER_API_URL` and `POWER_API_KEY` are all set).

## Verification

Factory call with the reported config (no `DEVICE_IP`): remotes = IRTrans + the unconfigured
external ones (skipped later), no `remote_android_tv`, no `verification_adb`, power =
`api_power`. With `device_ip` set, `remote_android_tv` and `verification_adb` come back.
