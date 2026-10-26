# BUG-0205 — An Apple TV wired to an IRTrans box got no remote, and a Fire TV always showed an IR panel

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                             |
|-----------|-------------------------------------------------------------------|
| ID        | BUG-0205                                                          |
| Reported  | 2026-09-28                                                        |
| Severity  | Medium — the device could not be driven from the panel at all     |
| Status    | Fixed (pending deploy)                                            |
| Area      | `shared/src/lib/config/device_capabilities.py`, remote panels     |
| Fixed in  | build 90145 |
| Commit    | `d47966813` `0c54bff88`                                           |

---

## Symptom

An `apple_tv` device with `DEVICE{n}_IR_IP` / `_IR_LED` / `_IR_TYPE` set (a networked
IRTrans box) came up with capabilities `av, verification` only, and Take Control showed
*"Unsupported device: apple_tv"*. The same box could not drive an `android_tv` either.
The reverse problem on `fire_tv`: the panel always drew an IR remote next to the ADB one,
even on a Fire TV with no IR transmitter configured, so its keys did nothing.

## Root cause

Which remotes a device can get was hand-written per model in `DEVICE_CONTROLLER_MAP`:
`irtrans_remote` was listed for `stb` only, `apple_tv` and `fire_tv` had lirc IR only,
`android_tv` had none. A transport the model did not list was never created, whatever the
`.env` said. And `DeviceControlPanels.tsx`, `RecPanelManager.tsx` and `NavigationEditor.tsx`
special-cased `device_model === 'fire_tv'` to always render `android_tv` + `ir_remote`
instead of reading the remotes the host actually created.

The IRTrans transport also required `DEVICE{n}_IR_REMOTE` (a remote learned in the box),
so an Apple TV with no learned remote was skipped even once the model accepted it.

## Fix

- One `EXTERNAL_REMOTES` list (`ir_remote`, `irtrans_remote`, `bluetooth_remote`) accepted by
  every HDMI/camera model: `stb`, `apple_tv`, `android_tv`, `fire_tv`, `android_tablet`,
  `tizen`, `camera`. The `.env` picks the transport (`IR_PATH` → lirc, `IR_IP` → IRTrans,
  `BLE_TYPE` → BLE); an unconfigured one is skipped.
- `DEVICE{n}_IR_REMOTE` is optional: without it IRTrans sends the `ir_conf/<IR_TYPE>.json`
  raw codes as Pronto/CCF (`sndccf`), so nothing has to be learned in the box.
- The three panels drop the `fire_tv` branch; one panel per remote in the device's
  reported capabilities.

## Verification

`create_controller_configs_from_device_info` for each model: with no IR/BLE keys only the
native remote is created (`android_tv` → `android_tv`, `apple_tv` → none); with `ir_ip` +
`ir_type` it adds `irtrans_remote`; with `ir_path` + `ir_type` it adds `ir_remote`.
`tsc --noEmit` clean. Not yet tried against a physical IRTrans box.

## Client patch

| Field | Value |
|-------|-------|
| Patch  | **patch-2** — `patch/patch_host_2_irtrans-any-device.sh` |
| Why    | A client install that predates the fix reports no remote at all for a non-`stb` device, and the fix has been on `main` for weeks. The patch puts it on one box without a full update. |
| Apply  | `bash patch-2.sh --check` → exit 10 means it is needed, 0 means already applied. Then `sudo bash patch-2.sh` (add `--no-restart` to restart later, `--no-raw-codes` for the capability fix alone). |
| Undo   | `sudo bash patch-2.sh --rollback` — restores each `<file>.patch-2.bak`. |
| Verify | `journalctl -u vpt-host -n 100 --no-pager \| grep -i irtrans`, then the device shows an IR panel in Take Control. |
| Log    | `/var/log/vpt-patches.log` |

The script embeds the four fixed files byte-for-byte rather than carrying a diff: a client of
unknown vintage will not apply an upstream diff (the pre-fix map differs too much), and whole
files always do. `--check` compares byte-for-byte, so a re-run is a true no-op. The next
normal update to the client supersedes the patch.
