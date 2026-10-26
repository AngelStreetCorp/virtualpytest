# BUG-0821 — A half-disabled device slot kills every stream on its host

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0821                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / stream                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-mf1 every live stream (appletv1, stbv1, stbv1+, Mi, S7, host VNC) froze and
dropped over and over, in LOW too, while the load average stayed at about 1.1 on 20 cores. The overlay
showed `FPS: out 0`. The `stream` journal showed about 200 watchdog restarts an hour,
`device1/2/3: 4 restarts within 300s → USB flapping` in the same second, then 600 s with no
picture.

## Root cause

device7 (Honor) had been disabled in the host `.env` by prefixing its keys with `x`, but
`DEVICE7_ADB_SERIAL` was left live. The grabber loop in `run_ffmpeg.sh` builds an ADB grabber
from `DEVICE<i>_ADB_SERIAL` alone, so device7 got a grabber with an **empty capture path**.

`kill_all_ffmpeg_for_device` kills `pkill -9 -f "$capture_dir/captures"`. With an empty
`capture_dir` that is `"/captures"`, which matches every device's ffmpeg. device7's scrcpy
never started, so the watchdog retried it about every 80 s, and each retry SIGKILLed all
12 ffmpeg processes on the host ("Found 12 process(es) to kill" for device7). 31 s later the
other devices looked stale and restarted. After 4 restarts in 5 min they were called
"USB flapping" and kept off for 600 s.

Same class as BUG-0285 (phantom slot with capture_dir ""), reached through the ADB branch.

## Fix

`backend_host/scripts/run_ffmpeg.sh`:
- the grabber loop skips any slot that has a source (`VIDEO` or `ADB_SERIAL`) but no
  `DEVICE<i>_VIDEO_CAPTURE_PATH`, with a `WARNING` line;
- `kill_all_ffmpeg_for_device` refuses an empty `capture_dir` instead of killing everything.

Hot fix on vpt-mf1: `DEVICE7_ADB_SERIAL` renamed `xDEVICE7_ADB_SERIAL`, `vpt-stream`
restarted (backup `.env.bak-2026-10-22-device7`).

## Verification

`sudo journalctl -t stream --since "-10 min" | grep -cE "stale ffmpeg|USB flapping"` on
vpt-mf1 drops from ~35 per 10 min to 0, and the newest `.ts` in every
`capture*/hot/segments` is a few seconds old.
