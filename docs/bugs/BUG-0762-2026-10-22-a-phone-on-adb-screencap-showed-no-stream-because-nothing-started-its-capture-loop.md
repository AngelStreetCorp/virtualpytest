# BUG-0762 — A phone on adb screencap showed no stream, because nothing started its capture loop

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0762                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / stream                                        |
| Fixed in  | build 90145 |
| Commit    | `264bbb4db` (main), patch-5                                  |

---

## Symptom

An Android phone on USB set up for adb screencap in the host `.env` (`DEVICE<N>_ADB_SERIAL` +
`DEVICE<N>_VIDEO=/var/www/html/stream/emulator_frames/device<N>/latest.png`) showed no stream.
On a client release from 2026-09-17, `install_service.sh emulator-fifo` also failed with
"Template file not found".

## Root cause

`vpt-stream` only reads `latest.png`; the loop that writes it, `vpt-emulator-fifo@device<N>`
(`emulator_screencap.sh`), is a separate systemd template and nothing enabled its instances: the
installer copied the template and left `systemctl enable` per slot as a manual step. Releases
before 2026-10-08 have no per-device loop at all, and before 2026-10-04 (BUG-0344)
`run_ffmpeg.sh` takes `DEVICE<N>_ADB_SERIAL` over `DEVICE<N>_VIDEO` and fails with
"Unknown source type for ADB".

## Fix

- `setup/local/linux/backend_host/ensure_screencap_loops.sh`, run by `vpt-stream.service` as
  `ExecStartPre=-+` (like `ensure_hot_mounts.sh`): starts `vpt-emulator-fifo@device<N>` for every
  screencap device in the `.env`, stops the loops of slots removed from it.
- **Client patch:** patch-5, `patch/patch_host_5_screencap-loop.sh`, for releases without the
  above: VIDEO wins over ADB_SERIAL in `run_ffmpeg.sh`, per-device `emulator_screencap.sh`, the
  template unit, the ensure script and a `vpt-stream` drop-in. Apply on the host:
  `bash patch_host_5_screencap-loop.sh --check && sudo bash patch_host_5_screencap-loop.sh`.
  The USB remote also needs patch-3 on those releases.

## Verification

- `systemctl is-active vpt-emulator-fifo@device<N>` is `active` after a `vpt-stream` restart, and
  `/var/www/html/stream/emulator_frames/device<N>/latest.png` keeps updating.
- patch-5 cycle tested on a copy of the 2026-09-17 files (stubbed systemd): `--check` needed (10),
  apply, `--check` already applied, apply again changes nothing, `--rollback` restores both files
  and removes what it added, `--check` needed again.
