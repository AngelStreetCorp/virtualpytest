# BUG-0485 — Switching stream quality hangs on "Loading HD quality stream..."

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0485                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend · rec · HLS player                                  |
| Fixed in  | Unreleased                                                   |
| Commit    | `418feeaf6`                                                  |

---

## Symptom

On vpt-mf1 (stbv1+), clicking LOW / SD / HD / HD+ in the stream window sometimes left the
"Loading HD quality stream... Waiting for stable stream" overlay up for a long time, sometimes
until the window was reopened. The console showed the new stream was ready within ~3 s
(`✅ Fresh stream ready ... gap=true, seqRestart=true`), preceded by
`Segment 404 error (n/10)` lines.

## Root cause

Two faults in `frontend/src/components/common/HLSVideoPlayer.tsx`:

1. When the switch completed (`shouldPause` true → false) the player called
   `setStreamLoaded(false); initializeStream()`. The stream URL does not change with quality and
   `streamLoadedRef` is only synced by an effect after the next render, so `initializeStream`
   hit its "Already loaded this URL" guard and did nothing. `onPlayerReady` — the only thing that
   clears the overlay — then waited for the old hls.js instance to fail fatally on the recycled
   manifest and retry after `retryDelay` (6 s).
2. While `shouldPause` was set the player only paused the `<video>`; hls.js kept fetching
   segments ffmpeg had just deleted. Ten 404s set `ffmpegStuck`, which destroyed the instance and
   made every later init refuse ("FFmpeg is stuck"), so the overlay stayed forever.

## Fix

During a switch the player also calls `hls.stopLoad()`. On completion it destroys the old
instance (`cleanupStream()`), and the existing "activated while not loaded" effect re-creates it
with a fresh closure; `MANIFEST_PARSED` fires `onPlayerReady` and the overlay clears.

## Verification

Open stbv1+ on vpt-mf1, switch LOW → HD → SD several times: the overlay clears a second or two
after `Fresh stream ready`, with no `Segment 404 error` lines during the switch.
