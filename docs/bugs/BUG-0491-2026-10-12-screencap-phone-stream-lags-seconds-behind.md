# BUG-0491 — A phone streamed by screenshots showed every change 3-4 s late

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0491                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host stream pipeline (run_ffmpeg.sh, imagefile source) |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In group control, a phone with no HDMI capture (an Android 8 handset streamed from
`adb screencap` PNGs) showed typed text, page loads and key presses 8-10 s after the
remote reported "Sent", long after the other phone of the group. On the host, a screen
change reached the device's `latest.jpg` thumbnail 4.6-5.7 s after the key press, while the
screencap PNG itself had it after 1.2-2.1 s. The stream's ffmpeg sat at 64% CPU and 1 GB RSS.

## Root cause

Two things in the `imagefile` branch of `backend_host/scripts/run_ffmpeg.sh`:

1. **Frame-threaded PNG decoder.** ffmpeg frame-threads the PNG decoder across every core by
   default, and each decoder thread holds one frame. On a 20-core host that is ~20 frames in
   flight; at the ~5 fps the `cat` loop delivers, ~4 s of lag (and the 1 GB of RAM). Measured
   offline with the same command: 4.07 s with the default, 0.68 s with `-threads 1`.
2. **Synthetic clock on devices without audio.** Frames were stamped N/10 s (`-framerate 10`)
   while only ~5 fps arrive, so without audio the stream's media time ran at half wall speed:
   a 0.4 s HLS segment took 0.8 s to fill and the player's 1 s behind the live edge was 2 s of
   real time. Wall-clock stamps were only applied when audio was on (BUG-0169).

## Fix

`run_ffmpeg.sh`, `imagefile` branch: `-threads 1` before `-i -` (single-threaded PNG decode,
a few tens of ms per full-HD frame); video always stamped with the wall clock
(`settb=AVTB,setpts=RTCTIME-RTCSTART` before the split, as BUG-0169 requires); keyframes
then the stream output resampled to a constant `-r $input_fps`, so `-g` keeps keyframes and
segments at 0.4 s. The JPEG outputs keep their 1 ms encoder time base (BUG-0165).

**Follow-up, same day — the first fix made the stream blocky.** It forced keyframes on the
wall clock but left the HLS output without a frame rate. The wall-clock time base has none,
so ffmpeg padded the output to 25 fps: 2.5× the frames for the same bitrate, one in three a
keyframe. The phone tile was full of macroblocks (SSIM against the source PNG 0.949 vs 0.986
before). `-r $input_fps` on the stream output restores 0.986 and keeps the lag (thumbnail
~0.5 s, HLS segment ~0.7 s after the PNG changes). Passing the frames through as VFR
instead is worse (SSIM 0.65): x264 sizes its bit budget for the microsecond tick. Devices
with audio (Android emulators) had the same 25 fps padding since BUG-0169 and get the same
fix.

## Verification

On the host, one adb key press (Settings / HOME, 4 runs), timed against the live thumbnail
(old pipeline) and a scratch ffmpeg with the fixed command reading the same PNG:

| | PNG updated | fixed pipeline | old pipeline |
|---|---|---|---|
| Settings | 1.3 s | 1.7 s | 4.6 s |
| HOME | 2.1 s | 2.5-2.6 s | 5.6-5.7 s |

The pipeline's own share drops from ~3.4 s to ~0.4 s. What remains before the PNG lands is
the phone's own transition and `adb screencap -p` (~0.65 s per frame on this handset; raw
screencap is slower over USB). After deploy: press a key on the phone in group control and the
tile follows within ~2-3 s.

**Follow-up 2 (2026-10-13): the S7 tile stalled in HD.** Two causes:

1. A leftover SSIM ffmpeg from the quality check above ran on the host for ~11 h at ~10
   cores (load 24 on 20 cores). Killed. It was a test process, not part of the platform.
2. Even after that, the HD tile stalled. The fixed clock had made the stream really send its
   1.5 Mbit/s: before, 0.4 s of half-speed media time was 0.8 s of real time, so it sent
   ~750 kbit/s. The host is a phone hub on 2.4 GHz WiFi. At 1.5 Mbit/s, ping from the proxy
   to the host reached 2-5 s, playlist fetches hit the player's 3 s timeout, and segments
   took 1.8-3.4 s to arrive for 0.4 s of video. A static phone screen costs its keyframes, so
   CRF does not help (1.5 Mbit/s at 0.4 s keys whatever the CRF).

   Screenshot streams now key and segment every 0.8 s at half the capture-card bitrate
   (HD 750k): 0.81 Mbit/s with SSIM 0.984, the same as before the clock fix. 750k at 0.4 s
   keys would be blocky (SSIM 0.962). `captures_per_segment` goes to 4 for `imagefile`, so
   capture numbering stays monotonic across restarts. Thumbnail lag is unchanged (~0.5 s);
   the HLS tile is back to ~2 s behind the phone.

   The link itself stays weak: the host should move to 5 GHz or Ethernet.
