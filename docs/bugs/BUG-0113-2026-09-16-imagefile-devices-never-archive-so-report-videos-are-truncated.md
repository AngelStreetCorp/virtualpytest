# BUG-0113 — Imagefile devices never archive, so their report videos are silently truncated

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                    |
|-----------|---------------------------------------------------------------------------|
| ID        | BUG-0113                                                                 |
| Reported  | 2026-09-16 (noticed while checking an unrelated line in a phone run's log) |
| Status    | Fixed — verified on host-clone-1                                          |
| Severity  | Medium (every emulator and every paired phone, silently)                  |
| Area      | `backend_host/scripts/run_ffmpeg.sh` (imagefile branch) + host provisioning |
| Fixed in  | build 9151                                                                |
| Commit    | TBD                                                                      |

---

## Symptom

A 94-second test against a paired phone produced a 30-second report video. The run passed, the
video played, and nothing in the UI said anything was missing. Only the log did:

```
need 94s | window 10:00:45→10:02:34 | HOT segments=31 in-window=30 @ 1.0s
  → HOT covers ~30.0s, COLD must fill 88.4s
COLD backfill empty: no chunks covered window ... (device has no COLD history)
FINAL VIDEO: 109.0s wall | media 30.0s | missing 79.0s
```

Comparing the two devices on the host made it plain:

| capture folder | `/hot` | `chunk_10min_*.mp4` |
|---|---|---|
| `capture` (device1, HDMI) | yes | 144, across 24 hours |
| `capture2` (the phone) | no | **0** |

## Root cause

Two layers, and the first one hid the second.

**1. No RAM hot storage for the slot.** `/hot` is a tmpfs at `<DEVICEn_VIDEO_CAPTURE_PATH>/hot`,
created by `setup/local/linux/backend_host/setup_ram_hot_storage.sh` — which **nothing calls**:
no installer, no deploy, no boot hook. It appears in the repo only in troubleshooting docs and
in error messages printed after something has already gone wrong. A device added to a host's
`.env` after the last manual run of that script lands in the archiver's "SD mode", where it
prunes but never archives. Not phone-specific: any device, any host.

**2. The real one — `hls_list_size 30` on the imagefile branch.** With hot storage in place the
archiver switched to `RAM (hot)` mode and still produced no chunks, because:

- the imagefile branch of `run_ffmpeg.sh` segmented at `-hls_time 1 -hls_list_size 30`, so the
  playlist only ever retained **30 one-second segments**;
- `hot_cold_archiver.py` builds its 1-minute MP4 from
  `segments_needed = max(1, round(60 / segment_duration))` = **60** segments;
- 60 > 30, so `merge_progressive_batch` never had enough, every cycle logged
  `1min MP4 not created (not enough segments yet or merge failed)`, and the entire chunk path
  (`if mp4_1min:`) was skipped.

COLD was therefore permanently empty for **every imagefile device** — emulators as well as
paired phones — and their report videos could never be longer than the live HLS window. Every
other source type already used `hls_list_size 150`.

## Fix

`backend_host/scripts/run_ffmpeg.sh`: imagefile `hls_list_size` 30 → **150**, matching every
other source type. 150 × 1s segments is roughly 300 KB of the hot tmpfs.

Provisioning is a documented step rather than a code change: `docs/technical/MOBILE_APP.md`
now warns, at the point where a slot is added, that a new slot needs
`setup_ram_hot_storage.sh` — per slot, not per pairing, since `/hot` belongs to the capture
folder and pairing a different phone onto an existing slot changes nothing.

**Mind the comments.** A `#` line placed between two backslash-continued lines of an ffmpeg
invocation ends the command early; the truncated filter graph then fails with
`Filter scale:default has an unconnected output`, and `bash -n` does not catch it. That is how
the first attempt at this fix took the phone's stream down. Explanations go above the `elif`,
never inside the command.

## Verification

On host-clone-1, after raising the retention and running the hot-storage script:

```
Created 1min MP4 (slot 1): /var/www/html/stream/capture2/segments/temp/1min_1.mp4 (0.62s)
Skipped MP3 (no audio in source): ...            ← handled, not a failure
Created 10min MP4: /var/www/html/stream/capture2/segments/10/chunk_10min_4.mp4 (0.43MB)
```

and the next run's video covered the whole test:

```
COLD chunk 10/4: media offset 53.6s = wall 10:41:34→10:43:07 (actual 92.7s of 91.8s requested)
merging COLD 10:41:34→10:43:07 + HOT 10:43:06→10:43:37 (46.0s)
FINAL VIDEO: window 123.0s wall | media 138.7s | missing 0.0s
```

`missing 79.0s` → **`missing 0.0s`**.

## Not a bug: the "Permission denied" lines alongside it

The same log showed `Failed to delete local file capture_*.jpg: [Errno 13] Permission denied`.
That was an artifact of running the script by hand as `jndoye`: `captures/` is `755
vpt_user:vpt_user`, and unlinking needs write permission on the directory. `vpt-host` runs as
`User=vpt_user`; the same run through the normal path logged zero permission errors. Run
scripts as `sudo -u vpt_user` when reproducing by hand.
