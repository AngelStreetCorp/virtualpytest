# BUG-0454 — WEB never plays in the app: MediaMTX answers `Access-Control-Allow-Origin: *` to a credentialed WHEP POST

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0454                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (vpt-pi1 live; other MediaMTX hosts per WEBRTC.md §1)  |
| Severity  | High                                                         |
| Area      | host infra — `/opt/mediamtx/mediamtx.yml` (not in the repo)  |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On virtualpytest.angelstreet.io, choosing **WEB** for STB4 on vpt-pi1 fell back to HLS, while
the standalone `scripts/whep_test.html` played the same stream over the same public route.

## Root cause

`whepActions.ts` sends the WHEP POST with `credentials: 'include'` (the host-session cookie, as
for HLS). MediaMTX was configured with `webrtcAllowOrigins: ['*']` and answered the preflight
with `Access-Control-Allow-Origin: *`. A browser refuses a credentialed response with a
wildcard origin, so the POST failed in the browser (`TypeError: Failed to fetch`) and MediaMTX
never created a session. The test page was opened as a file and sent no cookies, so it never
hit the rule — the test did not do what the app does.

## Fix

- vpt-pi1: `webrtcAllowOrigins` set to the platform CORS allowlist
  (`DEFAULT_CORS_ALLOWED_ORIGINS` in `shared/src/lib/utils/app_utils.py`). MediaMTX reloads the
  file live (RTSP and the ffmpeg publishers keep running); it now echoes an allowed origin
  with `Access-Control-Allow-Credentials: true` and sends no CORS header to others. Backup:
  `/opt/mediamtx/mediamtx.yml.bak.2026-10-11-cors`.
- `scripts/whep_test.html` sends cookies like the app and is served from
  `http://localhost:5073` (an allowed origin), so the test can no longer pass where the app fails.
- `docs/agent/devices/WEBRTC.md` §1 records the rule (never `'*'`); §4 item 3 is the check.
- vpt-pi3 (offline at fix time; config still `webrtcAllowOrigin: '*'`) and any other MediaMTX
  host need the same line.

## Verification

From a Mac outside the hosts' LAN, `whep_test.html?host=vpt-pi1&cap=capture4&public=1`:
- from `http://localhost:5073` (allowed): POST 201 at 0.29 s, video at 0.65 s, 1280×720, RTT 32 ms;
- from `http://127.0.0.1:5073` (not allowed): `TypeError: Failed to fetch`, console
  "blocked by CORS policy" — the failure the app had for every origin while the answer was `*`.
- `curl -X OPTIONS -H 'Origin: https://virtualpytest.angelstreet.io' …/host/vpt-pi1/whep/capture4/whep`
  → `access-control-allow-origin: https://virtualpytest.angelstreet.io`.
