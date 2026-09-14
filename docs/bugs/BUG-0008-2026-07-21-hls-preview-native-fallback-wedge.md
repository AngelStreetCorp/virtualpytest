# BUG-0008 — Rec preview stuck on "Loading stream…" while the modal plays the same stream fine

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0008                                                     |
| Reported  | 2026-07-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / HLSVideoPlayer                                    |
| Fixed in  | build 8713                                                   |
| Commit    | `649a28500`                                                  |

---

> Note: the fix commit message says "BUG-0007" — the ID was renumbered to BUG-0008 after
> an ID collision with the Jul 20 virtual-scripts bug logged in parallel on `feat/demo`.

## Symptom

On the Rec page (prod), a device's `RecHostPreview` card sometimes sits on "Loading stream…"
indefinitely — yet clicking it opens `RecHostStreamModal` and the very same stream plays
immediately with no error. Console shows the escalation:

```text
[HLSVideoPlayer] Watchdog: starved 8003ms (readyState=1), soft-resuming
… (repeats to 20000ms) …
[HLSVideoPlayer] Native playback error: { code: 4, message: 'PipelineStatus::DEMUXER_ERROR_COULD_NOT_PARSE' }
[HLSVideoPlayer] Autoplay failed: Failed to load because no supported source was found.   ← loops forever
```

## Root cause

Both components render the **same** `HLSVideoPlayer`; what differs is lifecycle. The preview
keeps one player instance mounted for the life of the page (memoized, paused via prop), while
the modal mounts a fresh instance on every open (`if (!isOpen) return null`). A fresh instance
always starts on the healthy hls.js path — which is why the modal always worked.

The long-lived preview instance could fall into a trap state:

1. A transient source stall starves the video; the watchdog soft-resumes for 20 s, then
   hard-restarts.
2. With the stream still stalled, hls.js hit a fatal error, and the fatal handler fell back to
   native playback because `supportsNativeHLS` was true. That detection used
   `canPlayType('application/vnd.apple.mpegurl') !== ''` — Chromium answers `'maybe'` but its
   native demuxer **cannot parse our live playlists**: setting `video.src = <m3u8>` fails with
   `DEMUXER_ERROR_COULD_NOT_PARSE` (MediaError code 4).
3. The trap is sticky: the native error handler bumped `retryCount`, max-retries "switched to
   native" again, and every later init short-circuited on
   `retryCount >= 2 && supportsNativeHLS || useNativePlayer` — nothing on the error path ever
   reset `useNativePlayer`. The player never returned to hls.js until page reload; even the
   watchdog just spammed `play()` on the dead element.

## Fix

`frontend/src/components/common/HLSVideoPlayer.tsx` (`649a28500`):

- New module constant `MSE_SUPPORTED` (`'MediaSource' in window`) — a pre-import proxy for
  `Hls.isSupported()`. With MSE present, hls.js is the only valid engine for `.m3u8`; native
  `<video src>` stays reserved for MP4 files and MSE-less browsers (iOS Safari).
- All three premature native entry points now gate on `!MSE_SUPPORTED`: the `retryCount >= 2 /
  useNativePlayer` shortcut in `initializeStream`, the hls.js fatal-error handler, and the
  max-retries path in `handleStreamError`. On MSE browsers each of them now restarts hls.js
  instead.
- `tryNativePlayback` refuses non-MP4 URLs on MSE browsers and clears `useNativePlayer`; a
  native playback **error** on an MSE browser also clears the flag — one bad fallback can no
  longer capture the player permanently.
- The genuine last resort is untouched: `!HLS.isSupported()` at init still routes to native.

## Verification

- `npx esbuild` transform of the edited file passes (no local `node_modules` for a full build;
  prod build validates at deploy).
- Code-path review: the exact logged sequence (starve → hard restart → fatal → native
  DEMUXER_ERROR → sticky loop) is unreachable on MSE browsers after the change — every branch
  that previously selected native now re-enters `initializeStream`'s hls.js path, which resets
  `retryCount` and self-heals once the source produces segments again.
- After deploy: reproduce a source stall (pause ffmpeg on a host >20 s, resume); the preview
  must recover to live video by itself instead of wedging on "Loading stream…".

## Follow-up — 2026-07-21: fatal media errors now recover in place

After the fix deployed, capture2 (host1) showed the correct new behavior ("Restarting
HLS after fatal error", no native wedge) but flapped between error overlay and playback: the
stream throws fatal `bufferAppendError` on the **audio** SourceBuffer, and the handler answered
every fatal error with a destructive teardown + reinit. hls.js has a designed in-place recovery
for the media-error class; the handler now tries `recoverMediaError()` first, then
`swapAudioCodec()` + `recoverMediaError()` on a second strike within 10 s, and only tears down
on a third — so a transient host-side hiccup no longer blanks the card. The repeated audio
`bufferAppendError` on that one capture device points at the host ffmpeg audio stream and is
worth checking (`/tmp/ffmpeg_output_<id>.log` on the host).
