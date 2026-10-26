# BUG-0637 — YouTube device streams video with no audio

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0637                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / capture                                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

A device fed by `DEVICE{i}_YOUTUBE_URL` (model `rtsp_video`, e.g. "YouTube live" on vpt-pi4)
plays video, but the monitor overlay shows `Audio: No` and the stream has no sound.

## Root cause

`youtube_resolve` in `backend_host/scripts/run_ffmpeg.sh` asked yt-dlp for
`bv*[vcodec^=avc1][height<=480][fps<=30]/b`. `bv*` is YouTube's video-only stream (itag 135 for
480p H.264); YouTube serves the audio as a separate stream. ffmpeg mapped `0:a`, which does not
exist in that input, so the HLS segments had no audio track.

## Fix

The format is now `bv*[...]+ba[acodec^=mp4a]/b`: yt-dlp prints the video URL and then the AAC
audio URL (itag 140). The audio URL is kept in `YT_AUDIO[device]` and passed as a second ffmpeg
input with the same `-re`, reconnect and `-ss` flags as the video, mapped with `-map 1:a:0`.
`/b` (one stream with both) stays the fallback, and an external `DEVICE{i}_VIDEO_AUDIO` still
wins.

## Verification

On the host, `ffprobe` on a fresh segment of the YouTube device lists an `aac` audio stream,
and the overlay shows `Audio: Yes`.
