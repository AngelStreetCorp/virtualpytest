# BUG-0141 — A farm slot that had never run stopped every other device on the host from streaming

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0141                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (deployed to host-clone-1; other hosts on next deploy)                 |
| Severity  | High (one new slot silently removed the stream, captures and report evidence of every device on the host) |
| Area      | `features/device-farm/backend_host/frame_pump.py`                           |

---

## Symptom

After adding a second farm slot (`device4`) and restarting, `active_captures.conf` was **empty** —
no device on the host was streaming — and `vpt-stream` printed, forever:

```
Waiting for valid source image (/var/www/html/stream/farm_frames/device4/latest.jpg)... attempt 21/60
```

`device2` (a phone), `device3` (the working farm slot) and `host` never started at all.

## Root cause

Two reasonable behaviours that are wrong together:

1. The host's grabber **will not start until its source image exists**, and waits ~2 minutes
   (60 attempts) before giving up. For a capture card or a paired phone the file is always
   there, so this has never mattered.
2. A farm slot's image is written by the frame pump **only while a session is open**, and the
   pump must never open one (an idle host with four slots would otherwise bill for four
   devices). So a slot that has never run has no file, by design.

A brand-new farm slot therefore has nothing for the grabber to open. And because grabbers are
started **in sequence**, the one waiting holds up every device behind it — the blast radius is
the whole host, not the new slot.

Worse, it is quiet. The run still passes: the device answers commands, the script navigates and
verifies, and the report is produced — with no screenshots and no video, or with a stale frame.
A green test with no evidence is the failure mode this feature exists to avoid.

## Fix

The pump seeds **one** frame at `start()` — a 631-byte black JPEG inlined as a constant, so it
needs no Pillow, no ffmpeg and no file on disk. It opens no session; it is the pump touching the
filesystem, not the farm.

It writes only when nothing is there. A real frame left by an earlier session is better evidence
than a black square and is never overwritten, which is also why `device3` was untouched when this
was deployed.

## Gate

Three unit tests in `tests/backend_host/test_device_farm.py`: the pump seeds a valid JPEG so the
grabber can start, seeding never calls `utils()` (no lease), and an existing real frame survives.
A fourth, pre-existing test asserted the pump wrote *nothing* while idle; it now asserts the
invariant that actually matters — **no session** — plus that the only thing written is small
enough to be a placeholder.

Verified on `host-clone-1` by reproducing it: delete `device4`'s `latest.jpg`, restart `vpt-host`
→ `device4: seeded a placeholder frame so the grabber can start before the first session`, 631
bytes on disk, `device3` untouched. Then restart `vpt-stream` → **zero** "Waiting for valid source
image" lines and all four grabbers up inside a second.

## Found while

Running the same navigation script against two vendors on one host
([TASK-20](../tasks/TASK-20-device-farm-integration.md) / [TASK-21](../tasks/TASK-21-browserstack-provider.md)).
The BrowserStack slot was new, so its first run reported PASS with a black screenshot — which is
what made the whole problem visible.
