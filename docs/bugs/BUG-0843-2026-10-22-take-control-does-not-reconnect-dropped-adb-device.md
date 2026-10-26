# BUG-0843 — Take Control does not reconnect an ADB device that dropped off

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0843                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Take Control on an ADB-over-TCP device (vpt-pi1, device at `192.168.1.29:5555`) gave no working remote.
On the host, `adb devices` listed nothing. Running `adb connect 192.168.1.29` by hand brought it back
(`192.168.1.29:5555 device`) and the remote worked again.

## Root cause

`AndroidMobileRemoteController` / `AndroidTVRemoteController` run `adb connect` only in `connect()`, which runs
when the controller is built at host start. Once the device drops off adb (Wi-Fi blip, device reboot, adb server
restart), `is_connected` stays `True`. `/host/takeControl` (`backend_host/src/routes/host_control_routes.py`)
then logs "already connected", `get_status()` fails because the device is missing from `adb devices`, and the
route reports the remote as unavailable without trying to connect again.

## Fix

In `/host/takeControl`, when the remote's `get_status()` fails, call `connect()` once more (for ADB over TCP that
runs `adb connect <ip>:<port>`) and check the status again. The failure reason from `get_status()` goes into the
toast warning when the reconnect does not help.

Second round (2026-10-23): `ADBUtils.connect_device()` (`backend_host/src/lib/utils/adb_utils.py`) recovers in steps,
least disruptive first:

1. `adb devices` does not answer in 10 s → `adb kill-server` + `adb start-server`. Only then: a restart drops every
   adb device on the host (screencap loops, Appium sessions), so a single missing phone never triggers it.
2. TCP target (`ip:port`) not in state `device` → `adb disconnect` when it is offline, then `adb connect`.
3. Still missing, and a USB-attached device has that Wi-Fi address (`adb -s <usb> shell ip -o -4 addr show`) →
   `adb -s <usb> tcpip <port>`, then `adb connect` again. A different phone on USB is never switched.

`adb usb` is not part of it: a device configured by USB serial stays listed on USB in tcpip mode too.
`controller_manager.py` warns at host start when `DEVICEn_ADB_SERIAL` and `DEVICEn_IP` are both set (the serial wins).
Tests: `tests/backend_host/test_adb_connect_recovery.py`.

## Verification

On vpt-pi1: `adb disconnect 192.168.1.29:5555`, then Take Control on the device. The host log shows
`Remote status failed, reconnecting...` and `adb devices` lists the device again; the remote works.
