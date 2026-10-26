# BUG-0782 — The host's VNC password is handed to the browser inside the stream URL returned by getAllHosts

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0782                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | backend / security                                      |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-07, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /device-control (data from GET /server/system/getAllHosts)
- **Viewport / theme:** n/a (API)

Steps to reproduce:

1. As an admin session, call `GET /server/system/getAllHosts?include_system_stats=true`.
2. Read `devices[].video_stream_path` of the host-level VNC device of host-clone-2.

**Expected:** A stream path with no credential in a query string.

**Actual:** `video_stream_path` is `/vnc_lite.html?password=<value>`: the password travels in a URL, so it lands in browser history and in any proxy or access log. The value is deliberately not reproduced here. `backend_server/src/routes/server_host_session_routes.py:103` already treats the direct hit as something nginx gates so the password need not travel in the URL. The finder also notes the same default-looking password is used for the Grafana admin account, whose login page is publicly reachable: rotating it is an owner decision.

Evidence:

- None (API / export finding; see the finding text).

## Root cause

Not diagnosed; evidence is the API response only (no screenshot, because it would show the credential).

## Fix

Not started.

## Verification

Repeat the steps above on the fixed build and confirm the expected behaviour, in the viewport and theme listed.
