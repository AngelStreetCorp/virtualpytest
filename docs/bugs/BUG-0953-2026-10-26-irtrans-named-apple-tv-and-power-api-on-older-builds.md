# BUG-0953 — Apple TV on a named IRTrans remote fails on older builds, and its power API is ignored

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0953                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / remote (IRTrans), shared / device capabilities, patch-2 |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

On a client host patched with patch-2, an Apple TV on the IRTrans box
(`DEVICE2_MODEL=apple_tv`, `IR_TYPE=apple_tv`, `IR_REMOTE=AppleTv`, `IR_LED=14`) answered every key
with `Command failed`, while the EOS STB on the same box (`IR_REMOTE` set too) worked and the same
key sent from the IRTrans web UI worked. The device's `POWER_NAME` / `POWER_API_URL` /
`POWER_API_KEY` lines gave it no power control.

## Root cause

- **IR.** With `IR_REMOTE` set the controller runs in named mode and loads
  `irtrans_conf/<IR_TYPE>.json`. A build before 2026-09-28 has only `irtrans_conf/stb.json`, so the EOS
  STB connects and the Apple TV logs `IRTrans keymap not found` at start-up and never connects. patch-2
  shipped `ir_conf/apple_tv.json` (the raw codes for `IR_REMOTE` unset) but not
  `irtrans_conf/apple_tv.json`. The remote's name in the box was never the problem: it only has to match
  `IR_REMOTE`.
- **Power.** `DEVICE_CONTROLLER_MAP` allowed `api_power` only on `android_tv`, `fire_tv_fireos`, `stb`
  and `camera`; `apple_tv`, `android_tablet` and `fire_tv_vega` listed `['tapo', 'wol']`, so the power
  API was skipped for them whatever the `.env` said.

## Fix

- `shared/src/lib/config/device_capabilities.py`: `EXTERNAL_POWER = ['tapo', 'api_power', 'wol']` for
  every model that had power, like `EXTERNAL_REMOTES`; the `.env` picks (`POWER_API_URL` → power API).
- `patch/patch_host_2_irtrans-any-device.sh`: also installs `irtrans_conf/{apple_tv,fire_tv,samsung}.json`,
  carries `EXTERNAL_POWER` in its `device_capabilities.py`, and its `irtrans.py` returns the failure
  reason (BUG-0951). `--rollback` now also removes the files the patch created.

## Verification

On a copy of the 2026-09-20 build: `--check` lists 8 files, apply writes and compiles them,
`apple_tv` power is `['tapo', 'api_power', 'wol']`, the three keymaps are identical to main, a second
run is "Nothing to do", and `--rollback` restores every original and removes the three new keymaps.
On the client: `journalctl -u vpt-host | grep -i irtrans` shows the Apple TV initialised with
`remote 'AppleTv'` and no "keymap not found"; Take Control shows the power button.
