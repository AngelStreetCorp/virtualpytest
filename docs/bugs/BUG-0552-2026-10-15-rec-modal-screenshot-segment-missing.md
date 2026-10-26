# BUG-0552 — Take Control modal screenshot fails with "video segment missing"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0552                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The camera button in the stream modal (seen on `stbv1+` on `vpt-mf1`) shows the toast
"Failed to take screenshot (video segment missing)" while the video plays. The AI image query
button silently does nothing in the same state.

## Root cause

`useRecCaptureActions` needs `currentSegmentUrl`, which only the modal's own HLS player reports
(`HLSVideoPlayer.tsx`, on `FRAG_LOADED`). Since `a46287179` ("preserve stream between preview and
modal") the modal can reuse the preview tile's stream (`persistentStream`), so it mounts no HLS
player of its own and the segment URL stays `null`. The host, the capture and the host API were
healthy: `POST /server/av/takeScreenshot` returned 200 in about 1 s.

## Fix

`frontend/src/hooks/rec/useRecCaptureActions.ts`: when there is no segment URL (and always for VNC),
(and always for WebRTC, which plays no HLS segments and would leave a stale one) the screenshot and the AI image query take the latest frame from `/server/av/takeScreenshot` with
`fast: true` (skips the host-side fingerprint pass; about 0.2 s instead of about 1.1 s on vpt-mf1).
When a segment is known the old segment-based path is unchanged.

Follow-up: the host overwrites one fixed file (`verification_source.jpg`) and serves it with `cache-control: public, max-age=14400`, so every click showed the first image again. The returned URL now carries a `?t=<ms>` query so the browser fetches the current frame.

## Verification

Open the stream modal on a device, press the camera button: the frame opens, no toast. Same for the
AI image query.
