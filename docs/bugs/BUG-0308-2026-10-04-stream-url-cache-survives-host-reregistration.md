# BUG-0308 — Live player 404'd after a host renamed its capture folders (server kept stream URLs 24 h)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0308                                                     |
| Reported  | 2026-10-04 (capture folders renamed to `captureN` on a host) |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — live streams unwatchable until a server restart     |
| Area      | `backend_server/src/routes/auto_proxy.py`, `server_system_routes.py::register_host` |
| Fixed in  | Unreleased                                                   |
| Commit    | `d5cc241570`                                                 |

---

## Symptom

A host's `DEVICEn_VIDEO_STREAM_PATH` values were changed from source-named folders
(`/host/stream/hls_theo_bbb`) to the `captureN` convention, and the host was restarted and
re-registered. Devices added at the same time played fine. Every device that existed before
showed "Loading stream..." with `GET …/stream/hls_theo_bbb/segments/output.m3u8 404`, after a
browser reload too and in a fresh browser.

## Root cause

The `av/getStreamUrl` proxy keeps each device's stream URL in an in-memory cache keyed
`host_name:device_id` for `LONG_TTL` (24 h). Nothing invalidated it. Re-registration refreshed
the host registry (`video_stream_path` was correct there and in the host's own
`/host/av/getStreamUrl` answer), but the proxy kept returning the cached old URL. Only devices
viewed before the change had a cached entry, which is why new devices worked.

## Fix

`auto_proxy.invalidate_stream_url_cache(host_name)` drops every cached URL of a host;
`register_host` calls it after a successful registration. It imports `routes.auto_proxy`, the
same module path `app.py` uses, so it clears the dict the proxy actually serves.

## Verification

- `py_compile` of both files.
- Before the fix, on the RPI1 server: the host returned `/host/vpt-nipogi/stream/capture16/...`
  for device16 while the browser, through the server, still requested `hls_tears_of_steel_hd`.
- After deploy: devices 1–16 of the host request `captureN` with no server restart needed for
  future renames.
