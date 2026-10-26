# BUG-0832 — "WebRTC unavailable — back on HLS" says nothing, links to the wrong page, and hides which device

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0832                             |
| Reported  | 2026-10-22                           |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium                               |
| Area      | frontend (live view, notifications)  |
| Fixed in  | build 90145 |
| Commit    | TBD                                  |

---

## Symptom

The bell showed **"WebRTC unavailable — back on HLS"** with no device and no host in it.
Clicking it took the operator back to the **24h Heatmap** page — the page that happened to be
open when the failure happened — instead of to the device whose stream had dropped. The only
record of what actually went wrong was a `console.warn` in the browser's developer console
(`WebRTC failed (timeout) — falling back to HLS`), which an operator without devtools open
never sees.

## Root cause

Four separate defects on one notification, reported as one unreadable message:

1. **The reason was discarded at the component boundary.** `useWhepStream` knew *why* the
   session gave up (`timeout`, `Failed to fetch`, an `RTCPeerConnection.connectionState`) and
   logged it — but only to `console.warn`. `LiveStreamSwitch`'s prop was typed
   `onWebRTCFailed?: () => void` and fired `onWebRTCFailed?.()` with **no argument**, so the
   reason never left the component. The caller could not report what it was never told.
2. **No identity in the message.** `RecHostStreamModal.handleWebRTCFailed` raised a hardcoded
   string, although `host.host_name`, `device.device_name` and `deviceId` were all in scope.
   Six devices falling back produced six identical, indistinguishable notifications.
3. **The link pointed at the wrong page.** `showError()` was called with no options, so
   `route()` fell back to `to = window.location.pathname + search`. The live view opens in a
   **modal**, which never changes the URL — so the "where is this" target was always the page
   underneath. Opened from the Heatmap, the notification linked to the Heatmap.
4. **The id collapsed every device into one row.** With no explicit id, `route()` built
   `` `${category}:${to}:${message}` `` — identical for every device on that page. `addToList`
   keeps one entry per id, so the second device to fail **replaced** the first. N devices
   failing looked like one, and there was no way to tell which.

## Fix

`frontend/src/utils/whepFallback.ts` (new, pure) builds the notice:
`"<host> · <device>: WebRTC unavailable (<why>) — using HLS"`, with a per-device id
(`webrtc-fallback:<host>:<device>`), `category: 'device'`, a scope of `{host_name, device_id}`,
and a **Show** action deep-linking to `/device-control?device=<host>/<device_id>` — the
existing deep link that selects that one device. An unrecognised reason passes through
unchanged rather than being hidden.

The reason is carried end to end: `useWhepStream` keeps `failReason` in state (set in the same
batch as `status: 'failed'`, cleared when a new target starts, and `'no WebRTC support in this
browser'` on the `RTCPeerConnection`-missing path), `useLiveTransport` passes it on,
`LiveStreamSwitch` calls `onWebRTCFailed(failReason ?? 'unknown')`. The callback type is
`(reason: string) => void` through `RecHostStreamModal`, `RecStreamContainer`, `RecHostPreview`
and `Rec.tsx`'s persistent-player state, so the persistent live view reports it too.

## Verification

`tests/frontend/WhepFallbackNotice.test.ts` (11 cases) and `tests/frontend/WhepFailReason.test.tsx`
(4 cases, jsdom, `useLiveTransport` mocked). Both discriminate: reverting the message to the
old hardcoded string, the id to the page-keyed one and `LiveStreamSwitch` to `onWebRTCFailed?.()`
makes **7 of the 15 fail**, with the failures quoting the old values
(`'WebRTC unavailable — back on HLS'`, `'/monitoring/heatmap'`). `tsc --noEmit`, eslint
(`--max-warnings 0`) and the neighbouring suites (Rec, RecStreamModalHeader, Dashboard: 36 tests)
are green.

## Notes

This is a **reporting** fix, not a transport fix: the fallback itself was always working
correctly — the picture keeps coming over HLS, which is why the Heatmap tiles stayed live. What
was broken was everything the operator used to find out *which* device and *why*. The underlying
WebRTC cause is still diagnosed the way `docs/agent/devices/WEBRTC.md` §4 describes (MediaMTX
log on the host, the CORS `curl`, the ICE probe) — the notification now at least names the host
and device to start from.