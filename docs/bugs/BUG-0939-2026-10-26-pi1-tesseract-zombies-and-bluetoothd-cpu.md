# BUG-0939 — vpt-pi1: zombie tesseract children and bluetoothd at 40-90 % CPU

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0939                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / host setup                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Reported by the TASK-164 agent as the likely source of the ~8 % "no screenshot from the device"
failures on vpt-pi1 (4 cores, load 4-8 from ffmpeg and the monitors):

- 579 `<defunct>` `tesseract` processes, all children of `subtitle_monitor.py` (PID up since
  2026-10-19), about 15 an hour in bursts during the busy hours.
- `/opt/bluez-cccpatch-v2/.../bluetoothd -d` at 40 % CPU in a 2 s sample (93 % reported), and
  ~950 journal lines a minute.

## Root cause

1. **Zombies.** `harden_pytesseract()` (`shared/src/lib/utils/tesseract_env.py`, 2026-10-15) replaces
   pytesseract's `kill()` with terminate → `wait(1)` → kill → `wait(2)`, then sets `returncode`. On a
   loaded Pi a child that is not gone 2 s after SIGKILL (uninterruptible I/O on the SD card) is marked
   finished anyway, so Python never waits for it again. In a normal run the timeout path reaps fine:
   30 forced timeouts at `nice 15` on vpt-pi1 left 0 zombies.
2. **bluetoothd.** WirePlumber in the login user's session (PID 2010) opened a new system-bus
   connection every ~12 s, registered ~150 A2DP/HFP endpoints and SDP records, got
   `RegisterProfile() failed: org.bluez.Error.NotPermitted` (HFP UUIDs already registered) and started
   over. bluetoothd runs with `-d`, so each round is also ~190 debug lines. `install_procon.sh` had turned
   that monitor off on vpt-pi1; its `--revert` (Switch moved to vpt-pi3, 2026-10-06) removed the files
   and the BLE remote setup never had its own.

## Fix

- `tesseract_env.py`: a child still alive after the SIGKILL wait goes to a daemon thread that calls
  `process.wait()`; `returncode` is only set once the child is reaped.
- `setup/local/linux/backend_host/install_patched_bluetoothd.sh`: turns the WirePlumber Bluetooth
  monitor off for every desktop user (`80-vpt-ble-disable-bluez.lua` for 0.4, `.conf` for 0.5) and
  restarts that user's WirePlumber. Different names from the procon files, so a procon `--revert`
  keeps them. Routing hint in `docs/agent/devices/BLUETOOTH.md`.

## Verification

- vpt-pi1, 2026-10-26: files written for the login user, `systemctl --user restart wireplumber`.
  bluetoothd 40 % → 0.0 % CPU, journal lines in 15 s: 0, WirePlumber no longer on the bus as a
  re-registering client; `hid-remote@hci0` and `hid-agent@hci0` active, hci0 UP RUNNING.
- After the host deploy, `vpt-monitor-subtitle` restarted to drop the 579 existing zombies (only the
  parent's exit releases them).
