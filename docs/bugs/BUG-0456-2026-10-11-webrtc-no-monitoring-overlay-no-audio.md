# BUG-0456 — WEB (WebRTC) view: no Monitoring overlay and no sound

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0456                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend rec modal + `backend_host/scripts/run_ffmpeg.sh`    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

With **WEB** selected in the rec modal, the Monitoring card (blackscreen / freeze / audio /
screen) disappeared, and the stream had no sound even with the speaker unmuted.

## Root cause

1. The Monitoring overlay was a prop of `EnhancedHLSPlayer`. `LiveStreamSwitch` replaces that
   whole player with `WebRTCVideoPlayer` once WebRTC plays, so the overlay went with it.
2. The v4l2 grabber's tee sent only video to MediaMTX (`select=v`), and the only audio
   encode was AAC, which WebRTC cannot carry. `WebRTCVideoPlayer` also hard-coded `muted`.

## Fix

- `RecStreamContainer` builds one monitoring layer (Monitoring card + host stats) used by the
  VNC path and, through the new `webrtcOverlay` prop of `LiveStreamSwitch`, by the WebRTC player.
- `WebRTCVideoPlayer` follows the page's mute button (falls back to muted if the browser refuses
  autoplay with sound).
- `run_ffmpeg.sh` v4l2 branch: two audio encodes of the grabber's ALSA input — AAC (output
  stream 1) for HLS and Opus (stream 2) for the RTSP slave; the tee selects `0,1` for HLS and
  `0,2` for RTSP.

## Verification

- On vpt-pi1, the same ffmpeg output shape with a synthetic source (lavfi testsrc + sine) into a
  throwaway MediaMTX: MediaMTX logged `is publishing to path 't', 2 tracks (H264, Opus)`; the HLS
  segments carry `h264` + `aac`.
- Frontend: `tsc --noEmit`, eslint and the i18n check pass. Live check after deploy: WEB on a
  device with HDMI audio shows the Monitoring card and plays sound when unmuted.
