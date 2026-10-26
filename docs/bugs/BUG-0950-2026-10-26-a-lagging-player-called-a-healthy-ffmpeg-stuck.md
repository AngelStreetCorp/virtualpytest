# BUG-0950 — A lagging player called a healthy ffmpeg "stuck" and stopped

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0950                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend / live player                                       |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The Eggs count device (vpt-lenovo1, capture3) showed "FFmpeg appears stuck. Stream restart required. Segment failures:
10/10" and the video stopped. The ffmpeg had been running for 14 h 45 min and was writing a valid segment (H.264,
320x180, 0.4 s) several times a second; the playlist answered 200.

## Root cause

Two windows that do not match, and a player that read the gap as a dead ffmpeg:

1. The playlist lists the last 375 segments (150 s) on the video-file branch (300 = 120 s on the others).
2. The hot folder keeps only 20-80 s of them: the archiver merges the oldest full minute of segments into the 24 h
   recording and **deletes** them (`archive_hot_minute`). Measured: 53-126 segments on disk; fetched through the public
   URL, the first entry of the playlist answered 404, entry 300 and the last answered 200.
3. A player that falls behind (a stall, a background tab, a host restart) asks for one of the deleted segments, hls.js
   steps to the next one, also deleted, and `HLSVideoPlayer` counted each 404 as "FFmpeg stuck". At 10 it destroyed
   the hls.js instance and asked for a restart.

## Fix

`HLSVideoPlayer` (live mode): on a segment 404, when the playhead is behind the live edge, jump to
`hls.liveSyncPosition` and `startLoad` from there. The next fragment that loads resets the counter (as before), so only
a stream whose newest segments are missing too reaches 10 and is called stuck.

Not changed here: the playlist still advertises more than the hot folder keeps, so the live slider cannot really go back
150 s on a host that archives video. Making the archiver keep what the playlist lists touches its timing-critical hot
loop and is left as a separate change.

## Verification

`tests/frontend/HLSSegmentArchived.test.tsx`: a 404 110 s behind the edge moves the playhead to the edge and restarts the
load, nine further scattered 404s after a loaded fragment show no banner and do not destroy the player; ten 404s at the
edge still show "FFmpeg appears stuck". Live: the egg modal opened headless plays segments at the live edge, all 200.
