# BUG-0168 — Viewers get 403 on every stream: `av/getStreamUrl` is a POST

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0168                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed in code, not yet released                              |
| Severity  | Medium                                                       |
| Area      | backend_server auth middleware (viewer read-only floor)      |
| Fixed in  | —                                                            |
| Commit    | —                                                            |

---

## Symptom

A user with the `viewer` role (what every self-signup gets, TASK-22) opens the device page:
every tile fails with `POST /server/av/getStreamUrl … 403 (Forbidden)` and the console shows
`[@hook:useStream] Error getting stream URL: Error: Forbidden`. The server logs
`⛔ viewer blocked from POST /server/av/getStreamUrl`.

Seen on the gcloud standalone VM on 2026-09-27, the first deployment where a fresh viewer
account was used on the device page with login enforced.

## Root cause

`enforce_viewer_read_only` rejects every non-GET request from a viewer unless the path is in
`VIEWER_WRITE_EXEMPT_PREFIXES`. `useStream` calls `/server/av/getStreamUrl` with POST because
the auto-proxy takes `host_name`/`device_id` in a JSON body — `auto_proxy.py` even rewrites it
to GET towards the host. The route reads a URL and writes nothing, but the floor only sees the
method.

## Fix

`/server/av/getStreamUrl` and `/server/av/getStatus` added to `VIEWER_WRITE_EXEMPT_PREFIXES`
in `backend_server/src/lib/auth_middleware.py`. `/server/system/vnc-info` is deliberately
**not** exempted: it hands back a credential (BUG-0164).

## Verification

Not yet: needs a backend_server image release and a viewer account on a login-enforced
deployment. Expected: the device page loads streams for a viewer; the VNC tile still prompts.
