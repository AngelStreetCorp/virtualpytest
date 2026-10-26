# BUG-0826 — device cards stuck on "Loading stream..." forever when the host 404s the manifest

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0826                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend / streaming                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/device-control` a device card shows **"Loading stream..."** indefinitely, with no error and no picture.
Reported on two devices at once:

- `FR Anime 2 — viaTelePaese (720p)` (`vpt-nipogi` / device20)
- `vpt-lenovo6-host` (`vpt-lenovo6` / device1)

Measured live with a headless probe: the `vpt-lenovo6-host` card read `Loading stream...` at t=4s, 8s, 12s …
**60s and counting**, `<video>` present with `readyState 0`, `currentTime 0`, no error text.

## Root cause

Three independent defects stacked, each of which alone turns a terminal failure into a permanent spinner.

**1. The manifest-404 handler erased its own message.** When hls.js reports a fatal `manifestLoadError` with
`code 404` — ffmpeg is not writing that capture at all — the handler did:

```ts
setStreamError('Stream manifest not found (404). Stream is unavailable.');
cleanupStream();   // …whose last act is setStreamError(null)
```

Both writes land in one React event handler and are batched, last one wins, so `streamError` was **always null**.
That combination — `streamUrl` set, `streamLoaded` false, no visible error — is precisely the state the
`Loading stream...` overlay renders on (`HLSVideoPlayer.tsx`). The branch written specifically to stop retrying
and explain the problem guaranteed a permanent loader instead.

**2. The destroyed instance re-armed the init loop.** Because the handler had just torn down the hls instance,
`streamLoaded` was false and `hlsRef.current` was null, so the "stream activated while not loaded" effect re-ran
`initializeStream()` and re-requested the same missing manifest every 6 s, indefinitely. The live probe recorded
a continuous stream of `404 …/capture1/segments/output.m3u8`.

**3. Nothing upstream could fail either.** `utils/apiClient.ts` called `fetch()` with no `AbortSignal`, so any
request that never settles left `useStream`'s `isLoadingUrl` true forever — its `finally` never ran. The card's
own error state was dead code: `RecHostPreview` guarded the error branch with an `error` `useState` that had **no
setter**, so it was permanently `null` and never rendered; the real `streamError` only reached a transient toast.
`DeviceStreamGrid` checked `isVnc && streamUrl` *before* `urlError`, and a VNC device keeps its cached URL for
24 h, so a broken VNC device showed "Loading..." with its cause hidden underneath.

Note the API itself was healthy throughout: `getStreamUrl` answered 200 in 79 ms (`vpt-lenovo6`) and 406 ms
(`vpt-nipogi`), and the pi4 server answered `getAllHosts` in 77 ms. The failure was entirely in how the client
represented "this will never load".

## Fix

- `HLSVideoPlayer.tsx` — call `cleanupStream()` **before** `setStreamError()` so the message survives, and add a
  `manifestMissingRef` guard in `initializeStream` that refuses to re-init a 404'd manifest. The guard is cleared
  by a URL change and by `handleManualRestart` (the parent's restart control, via `onRestartRequest`), so the
  terminal state is not a one-way door. The `Loading stream...` overlay now also excludes `manifestMissing`.
- `HLSVideoPlayer.tsx` — when the retry budget is exhausted, say so ("Stream unavailable after 5 retries") instead
  of leaving "Retrying..." on screen for work that has stopped.
- `utils/apiClient.ts` — every request now has a deadline (default `HTTP_CONFIG.LONG_TIMEOUT`, 60 s;
  `timeoutMs` overrides, `0` opts out, a caller-supplied `signal` always wins). Chosen over
  `DEFAULT_TIMEOUT` (30 s) because this client fronts LLM-backed endpoints (`/server/agent/voice/command`,
  `/server/action/execute`) whose work legitimately outlasts 30 s — the deadline is a hang-catcher, not a latency
  budget. Timeouts are re-thrown with the request URL and budget so callers surface something readable.
- `hooks/controller/useStream.ts` — 15 s budget on `getStreamUrl`; `isLoadingUrl` starts `true` when a device is
  already selected (the auto-fetch effect runs after first paint, so the first frame otherwise read as "settled,
  nothing available"); the `finally` only clears the flag when the response is not stale (a slow answer for a
  device the user left was clearing the flag of the device they were now looking at); deselecting clears the flag
  with the rest of the state.
- `components/rec/RecHostPreview.tsx` — removed the dead `error` state and render the real `streamError`, plus an
  explicit "No stream available" terminal state.
- `components/common/DeviceStreaming/DeviceStreamGrid.tsx` — check `urlError` before the VNC loading case.

## Verification

`tests/frontend/HLSManifestMissing.test.tsx` drives a fake hls.js, fires a fatal `manifestLoadError` 404, and
asserts the message survives, the spinner is gone, the re-init loop has stopped, and a restart still recovers.
Fails 2/3 against the pre-fix `HLSVideoPlayer.tsx` (confirmed by stashing the fix), passes 3/3 with it.

Two test-harness details worth keeping: the component reads `'MediaSource' in window` at **module scope**, so
jsdom needs the global set before the import (a static import is hoisted above any `beforeEach`); and the player
withholds the stream URL until `useHostSession` has minted its cookie
(`streamUrl = hostSessionReady ? rawStreamUrl : undefined`), which never resolves without a server, so the hook
is stubbed.