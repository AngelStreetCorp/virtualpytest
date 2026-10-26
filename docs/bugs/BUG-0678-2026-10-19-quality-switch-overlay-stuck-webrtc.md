# BUG-0678 — The "Loading HD quality stream…" overlay stayed up forever after a quality switch with WebRTC on

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0678                                                                                       |
| Reported  | 2026-10-19                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Medium (the stream was running but hidden behind a spinner until the modal was closed)         |
| Area      | `frontend/src/hooks/rec/useRecQualitySwitch.ts`                                               |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                                            |

---

## Symptom

In the stream modal with WEB (WebRTC) on, clicking LOW / SD / HD showed "Loading <level> quality
stream… Waiting for stable stream" and the spinner never went away. The console showed the switch
had worked: `Fresh stream ready for <host>-device1! 5 segments …`, then `WebRTC dropped
(disconnected) — reconnect 1`.

## Root cause

The overlay (`isQualitySwitching`) is cleared only by the HLS player's `onPlayerReady`. While a
quality switch is paused the HLS player skips init, and once WebRTC has reconnected and plays again
`LiveStreamSwitch` unmounts the HLS player, so no ready signal ever arrives. The restarted stream was
confirmed (the manifest poll succeeded) but nothing cleared the overlay. Without WebRTC the HLS player
reports ready about 1.5 s after the stream is confirmed and the overlay clears; a normal switch takes
about 6 s end to end.

## Fix

`useRecQualitySwitch`: when the manifest poll confirms the restarted stream, start a 3 s fallback that
clears the overlay if the player has not already reported ready. The fallback is cancelled by a ready
signal, by a new switch, and on close.

## Verification

Before: switch SD → HD with WEB on; the overlay stays after `Fresh stream ready` appears in the console.
After deploy: the overlay clears within about 3 s of `Fresh stream ready`, with WEB on or off.
