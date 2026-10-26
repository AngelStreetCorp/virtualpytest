# BUG-0542 — The caption playback player takes the archive hour from the browser's clock, not the host's

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                  |
|-----------|--------------------------------------------------------|
| ID        | BUG-0542                                               |
| Reported  | 2026-10-15                                             |
| Status    | Fixed (pending deploy)                                 |
| Severity  | Major (wrong video and wrong badge for any viewer outside the host's timezone) |
| Area      | frontend / caption playback (TASK-103)                 |
| Fixed in  | build 90145 |
| Commit    | see branch task103-verify                              |

---

## Symptom

The stream modal of a `caption_playback` device (vpt-pi1 stb3, host in Europe/Zurich) opened from a browser in UTC
played video **two hours old**, while the badge read `2:33 behind live`. The picture's own clock (a Swiss webcam
overlay, 08:19) was 2 h behind the real time (10:22 CEST). A viewer in the host's timezone never sees it.

## Root cause

The archive names its files by the host's wall-clock hour (`segments/<hour>/chunk_10min_<n>.mp4`, host
`Europe/Zurich`). `targetPosition()` took the hour from the browser's `Date` (`getHours()`), and the badge offset used
the browser's time of day, so the player asked for the browser's hour, found the same-named chunk from two hours
earlier in the rolling 24 h archive, and computed the badge against the same wrong clock: it was self-consistent and
therefore looked right. The first live proof of TASK-103 §6.10 accepted it for that reason.

## Fix

`hostOffsetMs()` reads the host clock offset from the newest manifest chunk (`end_time` wall clock against the epoch
`created`, rounded to 15 min); `targetPosition()` and the badge use the host's clock; the player does not start (and
captions are not requested) until the offset is known. Unit tests cover an offset of 0 and of +2 h.

## Verification

Open the stream modal of stb3 from a browser in UTC: the picture's on-screen clock now matches the host's local time
minus `delay_s`, and the badge reads `2:3x behind live`.
