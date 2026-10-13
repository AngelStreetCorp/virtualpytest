# BUG-0458 — Host & Devices form asks the operator to type DEVICE_VIDEO_AUDIO by hand

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0458                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | backend_host / server / frontend — host registration        |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD (branch `feature/auto-detect-grabber-audio`)             |

---

## Symptom

When the operator registers a host in *Settings → Host & Devices* and adds a new
device, the form has separate "Video Device" and "Audio Device" text fields. The
video path can be guessed (the operator looks at `ls /dev/video*`), but the audio
device is the kernel-assigned ALSA card number that shuffles across reboots —
`plughw:2,0` today, `plughw:4,0` tomorrow. The operator either SSHes into the
host to run `arecord -l`, or copies the value from `scripts/detect_grabber.sh`
on a separate screen, then pastes it by hand.

Cross-port pairings (HDMI audio coming from a different physical source than
the video) make the situation worse: even with the script's output in hand, the
operator has to know which USB port the audio actually lives on, and that's not
printed next to the matching video row.

The `scripts/detect_grabber.sh` tool already pairs each `/dev/videoN` with its
ALSA card by walking the USB topology, but the form never calls it. Every host
registration re-pays the same manual-entry tax.

## Root cause

The host's `.env` (`backend_host/src/.env`) is read and written entirely
through the form fields. The form had no path to surface a paired
`DEVICE_VIDEO` + `DEVICE_VIDEO_AUDIO` value to the operator; the only place
this pairing existed was the operator-facing bash script, and that was a
side-channel, not part of the registration flow.

A second issue surfaced during the fix: the bash script silently fails when
the user running it is not in the `video` group (every `v4l2-ctl` returns
"Permission denied", the loop's `caps` variable stays empty, and the script
prints an empty `VIDEO` table with no hint why). On vpt-mf1 this bit the lab
operator `jndoye` on 2026-10-11; the script was only producing the BLUETOOTH
and INFRARED sections. The fix surfaces the empty-grabber case in the UI so
the operator sees the count and a hint about group membership.

## Fix

- **`backend_host/src/lib/grabber_detect.py`** — Python port of
  `scripts/detect_grabber.sh`. Same USB-parent walk to pair UVC with UAC,
  same capture-bit filter via `v4l2-ctl --info`, same `/sys/class/bluetooth`
  and `/sys/class/lirc` walks. Returns JSON-friendly data.
- **`GET /host/system/grabbers`** — host endpoint that calls
  `detect_grabbers()` and returns the same shape the bash script prints.
- **`GET /server/settings/host-grabbers?host_name=...`** — server-side
  proxy through the same `call_host` plumbing `host-config` uses, so the
  frontend hits one URL regardless of which host the operator selected.
- **`useSettings`** — new `loadGrabbers(hostName)` +
  `applyGrabberToDevice(grabber, deviceKey?)` helpers. The `deviceKey` arg
  is optional; if missing, the next device with no `DEVICE_VIDEO` set is
  picked, so a one-click "Use" on a fresh page just works.
- **Settings page** — new "Detected Grabbers" panel above the device list.
  Each row shows `video | audio | USB ID | port` and a `Use` button. Used
  grabbers (their `video` path matches an existing `DEVICE_VIDEO`) are
  marked "in use by DEVICE1" with the button hidden. Bluetooth and IR
  sections are also surfaced (informational — they don't auto-fill into
  the host .env).
- **`scripts/detect_grabber.sh`** — unchanged. Still the operator-facing
  CLI for eyes-on debugging; the Python module is the programmatic surface.
- **`tests/backend_host/test_grabber_detect.py`** — three test cases:
  pairing + filtering with a fake sysfs tree mirroring the real
  layered-symlink layout, empty-sysfs returns empty lists, and a missing
  `v4l2-ctl` filters out every video node (the same silent failure mode
  the bash script had — now explicit in a test).

## Verification

On vpt-mf1 with the new module deployed:

```
$ python3 -c "from backend_host.src.lib.grabber_detect import detect_grabbers; \
    import json; print(json.dumps(detect_grabbers(), indent=2))"
{
  "grabbers": [
    {"video": "/dev/video0", "audio": "plughw:1,0", "has_audio": true,
     "usb_id": "345f:2130", "usb_path": "3-1", "vendor": "345f", "product": "2130"},
    {"video": "/dev/video2", "audio": "plughw:2,0", "has_audio": true,
     "usb_id": "345f:2130", "usb_path": "3-2", "vendor": "345f", "product": "2130"},
    {"video": "/dev/video4", "audio": "plughw:3,0", "has_audio": true,
     "usb_id": "534d:2109", "usb_path": "3-5", "vendor": "534d", "product": "2109"},
    {"video": "/dev/video6", "audio": "plughw:4,0", "has_audio": true,
     "usb_id": "345f:2109", "usb_path": "3-4", "vendor": "345f", "product": "2109"}
  ],
  "bluetooth": [
    {"name": "hci0", "mac": "2C:1B:3A:BC:B6:F2", "usb_id": "0e8d:c616", "usb_path": "3-10"},
    {"name": "hci1", "mac": "20:21:41:00:1F:41", "usb_id": "050d:065a", "usb_path": "5-2"},
    ...
  ],
  "infrared": []
}
```

Identical to the bash script's output on the same host.

## Operator note

The host user that runs `vpt-host` must be in the `video` and `audio`
groups for `v4l2-ctl` to enumerate capture devices. The repo's
`setup/local/linux/backend_host/setup_permissions.sh:61` does
`usermod -aG video,audio,render $TARGET_USER` for that user. If the
panel reports zero grabbers on a host that visibly has HDMI capture
dongles plugged in, run `sudo usermod -aG video,audio vpt_user` (or
whichever user the service runs as), restart `vpt-host`, and click
*Rescan* in the panel.
