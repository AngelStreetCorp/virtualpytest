# BUG-0825 — Live stream stalls and drops frames on a host behind a slow link

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0825                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend_host / stream                             |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-mf1 (2.4 GHz WiFi, reached through vpt-pi1), appletv1 in LOW showed "FPS 62 · 31 drop"
and kept freezing for a moment. In WebRTC the picture froze too, and no latency was shown.
The host itself was fine: ffmpeg at 60 fps, `drop=0`, load ~1 on 20 cores.

## Root cause

Measured from the Mac with headless Chromium on the real stream:

- **HLS.** Every 0.4 s segment costs a playlist fetch plus a segment fetch. Median request
  ~150-200 ms, but p90 ~600 ms and up to 1.9 s, almost all from the WiFi hop
  (vpt-pi1 → vpt-mf1: p50 71 ms, p90 277 ms, max 1.5 s). The live playlist lists ~300 segments
  and was sent uncompressed (28 KB, more than the 11.6 KB segment) on every refetch. With a 1 s
  target the player ran dry (7-10 s waiting per 74 s), then caught up at up to 1.5x; at 1.5x a
  60 fps stream needs 90 frames/s on a 60 Hz screen, so the browser dropped ~30 a second.
  hls.js raises its target after a stall, but by at most one target duration, which ffmpeg
  writes as `TARGETDURATION:0` (read as 1) for 0.4 s segments, so it never got past ~2 s.
- **WebRTC.** Delay was low (jitter buffer ~80 ms, RTT ~50 ms), but the link loses packets
  (34-69 lost, 84-334 NACKs per 40-80 s). With an ~80 ms buffer a resent packet often arrived
  too late: 12.8 s frozen in 39 s, 32.2 s in 79 s.
- The WebRTC overlay had no latency row: the HLS one is measured from the `<video>` buffered
  range, which a WebRTC MediaStream does not have.

## Fix

- `backend_host/src/routes/host_stream_routes.py`: the live `.m3u8` is gzipped when the client
  accepts it (28 KB → ~1.9 KB).
- `frontend/src/components/common/HLSVideoPlayer.tsx` + `hlsLiveConfig.ts`: on the first live
  stall the target goes from 1 s to 3 s (`LIVE_STALL_TARGET_LATENCY_S`) and the playhead steps
  back into the loaded buffer at once; `liveMaxLatencyDuration` 3 → 8 so the 3 s target is not
  jumped back; catch-up rate 1.5x → 1.1x. A clean link never stalls and keeps 1 s.
- `frontend/src/actions/webrtc/whepActions.ts`: the first time a session loses packets or
  freezes, the receivers' `jitterBufferTarget` goes to 500 ms (`WHEP_LOSSY_JITTER_BUFFER_MS`).
  A clean link keeps the low default.
- `useWebRTCStats.ts` + `StreamStatsOverlay.tsx`: the jitter buffer is read over the last
  window, and the WebRTC block shows `Latency ~X s` (jitter buffer + half the RTT).

## Verification

Headless runs on vpt-mf1 capture1, 74-80 s each, back to back:

| Run | Waiting (stalled) | fps | Notes |
|-----|-------------------|-----|-------|
| HLS before (gzip off) | 7 s / 34 s | 50 | |
| HLS 1 s target, gzip on | 4-10 s / 74 s | 56-59 | sped up 16-26 s |
| HLS 3 s target from start | 0-1 s / 74 s | 60-61 | |
| HLS adaptive + step back | 1 s (the switch) + link outage | 56 | clean between |
| WebRTC default buffer | 32.2 s frozen / 79 s | 49 | |
| WebRTC adaptive 500 ms | 9.2 s frozen / 79 s | 54 | switched at 2 s |

A link blackout of 7-8 s seen on every run (vpt-mf1's WiFi) is not covered by any buffer; the
real fix for that is a cable or 5 GHz at vpt-mf1 (the 5 GHz band of its router is not visible
there; its Ethernet port goes to a switch with no DHCP).
