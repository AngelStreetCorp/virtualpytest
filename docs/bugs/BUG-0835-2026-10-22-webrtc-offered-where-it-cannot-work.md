# BUG-0835 — The WEB toggle was offered on every device, including where WebRTC cannot work

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0835                             |
| Reported  | 2026-10-22                           |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium                               |
| Area      | frontend + backend_host (live view)  |
| Fixed in  | build 90145 |
| Commit    | TBD                                  |

Follow-on to [BUG-0832](BUG-0832-2026-10-22-webrtc-fallback-notification-names-no-device.md),
which made the WEB→HLS fallback legible. This fixes the underlying cause: the transport was
being offered where it was never going to work.

## Symptom

Every device showed a **WEB** button next to LOW / SD / HD, on every host, with no
capability check. On `host-clone-1` — where `vpt-mediamtx` is inactive and
`/opt/mediamtx/mediamtx.yml` does not exist — pressing it is a guaranteed 6 s
`WHEP_CONNECT_TIMEOUT_MS` timeout and then a fallback to HLS, on the two cloud farm devices
(`Sauce_S23_FE`, `BStack_S23`) just as much as on a real capture.

## Root cause

Three gaps stacked:

1. **The capability field was never populated.** `stream_protocol` was declared in
   `frontend/src/types/common/Host_Types.ts` and read by `useStreamTransport`, but it appeared
   in **zero** backend files — no `.py`, no `.env` template, no provisioning. The branch
   "default to WebRTC when the registry says `whep`" was dead code.
2. **The backend could not have answered anyway.** There was no MediaMTX awareness anywhere:
   `vpt-mediamtx` is not in `build_service_health_summary`'s service list, and nothing probed
   for a WHEP endpoint. Nothing could distinguish a host that can do WebRTC from one that
   cannot.
3. **The toggle ignored all of it.** `StreamQualityControl` rendered WEB whenever
   `!restartMode && !isDesktopDevice`, gated only on `isLiveMode`. No check on the device's
   source, the host's services, or whether the device is a cloud farm at all.

Verified on `host-clone-1` 2026-10-22 with its own config: `device3` (saucelabs) and
`device4` (browserstack) both derive `cloud_farm`. The reason is stronger than "not v4l2" —
**their picture is not a stream at all.** Each is a single JPEG (`farm_frames/deviceN/latest.jpg`)
rewritten once a second (`DEVICE3_FARM_SCREENSHOT_FPS = 1`), which run_ffmpeg.sh ingests as an
`imagefile`. WebRTC buys sub-second latency over a source that refreshes every second, so even
with MediaMTX installed and publishing it would have nothing to gain here. `device2`
(`phone_frames`, a local capture) is `hls_no_webrtc_host` — correct too, this host has no
MediaMTX — but for a farm the honest answer is "no stream to carry".

Only the **v4l2** branch of `backend_host/scripts/run_ffmpeg.sh` emits the RTSP slave
(`rtsp://127.0.0.1:8554/<captureN>`) that MediaMTX serves, so anything else — ADB screencap,
x11grab, imagefile, network feeds — produces HLS and nothing for MediaMTX. A cloud device farm
has no stream of ours at all: `FarmProvider` has no stream method, and its `video_url` is a
*recording link* the vendor's jobs API returns once a job has finished.

## Fix

**A declared profile per device, computed from two real facts.**

- `shared/src/lib/utils/stream_capability_utils.py` (new, pure) — `derive_stream_protocol()`
  returns `whep` only when the host has a WHEP endpoint *and* the capture is a v4l2 grabber;
  `cloud_farm` for a device leased from Sauce Labs / BrowserStack (checked first, so an
  operator is never told to install MediaMTX for a device that runs in someone else's
  datacentre); `hls_no_webrtc_host` and `hls_no_publisher` for the two failure modes, which
  have different fixes.
- `backend_host/.../system_info_utils.py` — `has_webrtc_endpoint()`: honours the
  `WEBRTC_ENABLED` kill switch `run_ffmpeg.sh` already reads, requires the MediaMTX config,
  reads `webrtcAddress` from it, and probes that port once on loopback. Published as
  `system_stats['webrtc']`, next to `hardware_encode` which gates HD+ the same way.
  Deliberately not `systemctl is-active` — that forks on every stats cycle.
- `backend_host/.../host_utils.py` — stamps `stream_protocol` onto each device dict in the
  ping, the one place that holds both the host fact and the device facts.
- `backend_server/.../server_system_routes.py` — carries `system_stats.webrtc` and the device
  `stream_protocol` in the lightweight payloads, so the gate applies on first paint.

**The UI respects it.** `frontend/src/utils/streamCapability.ts` (new) mirrors the profiles
and gives each denial its own operator-facing sentence. `StreamQualityControl` shows WEB
**disabled with the reason on hover** rather than hiding it — an operator who cannot find the
button needs to be told why — and `useStreamTransport` forces HLS and forgets any stored
`webrtc` choice for a denied device, so a device switched before the host was probed stops
asking.

**Fail-open on purpose.** `undefined` and `hls` mean "this host has not reported yet" and keep
today's behaviour. Gating strictly on `whep` would have deleted WebRTC from every lab v4l2
device between the frontend deploy and the host deploy.

## Verification

- `tests/backend_host/test_stream_capability.py` — 7 cases over the derivation, including the
  farm-before-host ordering and the fail-open default.
- `tests/frontend/StreamCapability.test.ts` (10), `StreamTransportCapability.test.tsx` (7,
  incl. the stale-localStorage case), `StreamQualityCapability.test.tsx` (6, the rendered
  button). 30 new tests total.
- **They discriminate.** Reverting the deny set, the derivation, the force-HLS effect and the
  component gate fails **13 of them**.
- `tsc --noEmit`, eslint `--max-warnings 0`, ruff `E9,F63,F7,F82`, and the neighbouring suites
  (Rec, RecStreamModalHeader, Dashboard, Whep: 51 tests) green.

## Deploy note

The gate only takes effect once a **host** reports the profile: `update_core.sh main --frontend`
alone deploys the UI, which then fails open and behaves as before. Hosts must be updated too
for WEB to be withheld.