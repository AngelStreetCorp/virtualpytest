# BUG-0943 — The delayed stream waited for captions before playing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                          |
|-----------|--------------------------------|
| ID        | BUG-0943                       |
| Reported  | 2026-10-26                     |
| Status    | Fixed (pending deploy)         |
| Severity  | Medium                         |
| Area      | frontend                       |
| Fixed in  | build 90145 |

## Symptom
A `caption_playback` device (vpt-lenovo5 device6) showed live video in the grid, but its stream modal sat on "Waiting for the archive…".

## Cause
`CaptionPlaybackPlayer` refused to start until the host had a captioned minute (`limit > 0`) and paused at the last captioned minute. The archive chunks were there and playable; the host had transcribed no minute for the device, so the picture never started.

## Fix
Captions no longer gate the picture. The player starts from the archive chunk at `delay_s` behind live and always plays; the "Waiting for captions…" badge only says the current minute has no captions yet.
