# BUG-0165 — Emulator streams stalled at the first frame after emulator audio was added (regression)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0165                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host (`run_ffmpeg.sh`, imagefile / emulator capture) |
| Fixed in  | Unreleased                                                   |
| Commit    | `d38adc77a`                                                  |

Regression of `1d3581ffe` ("the emulator's own sound reaches the host", build 9151).

---

## Symptom

Android emulator devices with audio enabled (`labox-dongle`'s `labox-tv`, `labox-mobile`) showed no
live stream. Fleet health reported them `DEGRADED — capture layer: No JSON analysis files found
(monitor not running or no frames yet)` every day from 2026-09-22 / 09-23 onward.

The capture source was healthy: `emulator_frames/latest.png` was rewritten every second. But
`vpt-stream` restarted ffmpeg about once a minute (`✅ recovered` → `⚠️ stale ffmpeg log_age=54s`).
After four restarts it logged `🌀 ... USB flapping ... backing off 600s`. That label is the
watchdog's generic restart-count message, and an emulator has no USB grabber. `hot/segments/`
stayed empty, and restarting `vpt-stream` changed nothing. The ffmpeg log showed:

```
frame=    1 fps=0.0 ... time=00:00:00.20
[image2 @ ...] Application provided invalid, non monotonically increasing dts to muxer in stream 0: 1 >= 1
[mjpeg @ ...] Invalid pts (1) <= last (1)
Error submitting video frame to the encoder
```

## Root cause

`1d3581ffe` added emulator audio. To keep the picture in step with the sound, it stamped the
emulator frames with the wall clock (`settb=AVTB,setpts=RTCTIME-RTCSTART`, the `video_clock` in
`backend_host/scripts/run_ffmpeg.sh`, imagefile branch). It applied this at the head of the
filter graph, before `split=3`, so the capture and thumbnail branches got wall-clock
timestamps as well.

Those two branches encode mjpeg into `image2` with `-fps_mode passthrough`, at a time base of
`1/DEVICEn_VIDEO_FPS` (200 ms at 5 fps). The `cat` loop feeding ffmpeg delivers frames with jitter,
so two frames often arrive within one 200 ms tick. Both round to the same pts, the mjpeg encoder
rejects the second, and ffmpeg stops producing output. The HLS branch is VFR and was never the
problem.

The docs had no entry for it: the emulator runbook's "FFmpeg stuck" section only covered a broken
screencap / ADB side.

## Fix

`backend_host/scripts/run_ffmpeg.sh`: move `${video_clock}` from `[0:v]` onto the `[str]` branch.
The HLS stream (the only output carrying audio) keeps the wall clock, so audio stays in sync. The
capture and thumbnail branches get the synthetic constant-rate clock back.

Runbook added: `docs/android-emulator-troubleshooting.md` §10. Pointer added in
`docs/agent/devices/FFMPEG_TROUBLESHOOT.md`.

## Verification

A/B test on an affected host with the same frames for 12 s each, same filter graph as production:

| Variant | HLS segments | Captures | pts errors |
|---|---|---|---|
| Wall clock before `split` (regression) | — | 12 | 18 |
| No wall clock (pre-`1d3581ffe`) | — | 51 | 0 |
| Wall clock on `[str]` only (this fix) | 7 | 50 | 0 |

After deploying, on each emulator host: `hot/segments/` receives new `segment_*.ts` files,
`/tmp/ffmpeg_output_device1.log` has no `Invalid pts`, and the vpt-stream log no longer cycles
`stale ffmpeg` restarts.

Deployed to `labox-dongle` and `labox-mobile` on 2026-09-27. Both hosts had the unmodified pre-fix
script; only `run_ffmpeg.sh` was replaced, with a `.bak-bug0165` kept beside it. Result: one
continuous ffmpeg run past 90 s (the old failure point was 54 s), 5.0 fps, 0 pts errors, the newest
HLS segment current, and segments still carrying both `h264` video and `aac` audio.
