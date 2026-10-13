# BUG-0453 — WEB: "Loading WebRTC stream..." appears seconds after the click

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0453                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend — WebRTC live view (`useLiveTransport`, `whepActions`) |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Clicking **WEB** in the rec modal left the HLS picture on screen with no feedback; the
"Loading WebRTC stream..." overlay showed up only a few seconds later, and the WebRTC picture
followed about 2 s after the click at best.

## Root cause

1. `useLiveTransport` passed `null` to `useWhepStream` until `useHostSession` had minted the
   host-session cookie (`POST /server/host-session/session`). With a null URL the status stayed
   `idle`, and the overlay in `RecStreamContainer` is shown only for `connecting`.
2. `openWhepSession` then waited the full `WHEP_ICE_GATHER_MAX_MS` (1 s) before POSTing the offer,
   because Chrome rarely reaches `iceGatheringState === 'complete'` (see BUG-0449).

## Fix

- `openWhepSession` mints the host-session cookie itself (`ensureHostSession`) before the offer;
  `useLiveTransport` passes the WHEP URL straight to `useWhepStream`, so the status is `connecting`
  on the click and the overlay shows at once.
- `waitForIceCandidates` sends the offer on the first server-reflexive candidate (normally ~50 ms),
  on `complete`, or at the 1 s cap.

Files: `frontend/src/actions/webrtc/whepActions.ts`, `frontend/src/hooks/controller/useLiveTransport.ts`,
`frontend/src/constants/webrtcConstants.ts`, `scripts/whep_test.html`.

## Verification

`scripts/whep_test.html` with the same gathering logic, vpt-pi1 / capture4 (STB4), public candidate
only, from a Mac outside the hosts' LAN: offer POSTed at 0.3 s (was 1.27 s), video playing at
0.75 s (was 1.8 s), 1280×720, RTT 27 ms.
