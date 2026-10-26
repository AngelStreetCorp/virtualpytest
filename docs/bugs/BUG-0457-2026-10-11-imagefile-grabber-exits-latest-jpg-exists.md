# BUG-0457 — Emulator/phone grabber dies after a vpt-stream restart: "latest.jpg already exists"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0457                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / stream                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

After `systemctl restart vpt-stream` on vpt-mf1 (2026-10-11 13:01), devices 6 and 7 (S7, Honor:
`DEVICEn_VIDEO=.../emulator_frames/deviceN/latest.png`) had no ffmpeg and no live picture.
`/tmp/ffmpeg_output_device6.log`:

```
File '/var/www/html/stream/capture6/hot/thumbnails/latest.jpg' already exists. Exiting.
Error opening output file /var/www/html/stream/capture6/hot/thumbnails/latest.jpg.
```

## Root cause

The imagefile branch of `backend_host/scripts/run_ffmpeg.sh` was the only grabber command
without `-y`. Its `-update 1` output `thumbnails/latest.jpg` (TASK-48) survives a restart, and
ffmpeg asks before overwriting an existing file; stdin is the `cat` frame pipe, so it cannot
ask and exits. Every retry hits the same file.

## Fix

`-y` on the imagefile ffmpeg command, like every other grabber.

## Verification

On vpt-mf1: restart `vpt-stream`; devices 6 and 7 have a running ffmpeg, a fresh
`hot/segments/output.m3u8` and a `latest.jpg` with a new mtime.
