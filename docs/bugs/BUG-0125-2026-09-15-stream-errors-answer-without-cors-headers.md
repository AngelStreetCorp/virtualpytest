# BUG-0125 — A missing stream reports "blocked by CORS policy" instead of 404, so one dead device looks like a broken site

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0125                                                                    |
| Reported  | 2026-09-15 (found while investigating a missing stream on `vpt-pi1` / `S21x`, see [BUG-0101](BUG-0101-2026-09-15-ffmpeg-watchdog-blind-to-stalled-input.md)) |
| Status    | Fixed                                                                       |
| Severity  | Medium (no data loss; it misdirects the diagnosis — a single device with no manifest presents as a site-wide CORS misconfiguration) |
| Area      | `backend_host/src/routes/host_stream_routes.py` — stream/VNC routes          |
| Fixed in  | build 9151                                                                  |
| Commit    | `0bcb1e73a5`                                                                |

---

## Symptom

A device whose capture had stopped showed no stream, and the browser console reported the
request as **blocked by CORS policy** rather than as a 404. Three sibling devices on the same
host worked, so the failure read as a proxy or CORS misconfiguration of the whole site — while
the actual fault was one device with no manifest to serve.

## Cause

The stream routes attached `Access-Control-Allow-Origin` next to each `send_from_directory`,
i.e. only on the success path. Every error response — a bare `jsonify(...)` for 400/404/500 —
therefore went out with **no CORS header at all**.

A cross-origin caller never sees such a status: the browser refuses to expose a response that
carries no `Access-Control-Allow-Origin` and reports it as a CORS failure. The real status code
is unobservable from the page, so "this one file is missing" and "this whole origin is
misconfigured" look identical from the only place anyone is looking.

## Fix

`0bcb1e73a5` moves the headers to a single `@host_stream_bp.after_request`, which covers error
responses as well as served files:

```python
response.headers.setdefault('Access-Control-Allow-Origin', '*')
response.headers.setdefault('Access-Control-Allow-Methods', 'GET, OPTIONS')
response.headers.setdefault('Access-Control-Allow-Headers', 'Content-Type, Range')
response.headers.setdefault('Access-Control-Expose-Headers', 'Content-Length, Content-Range')
```

`setdefault` so a header already set on the success path (an explicit origin) is never
duplicated or overridden — two `Access-Control-Allow-Origin` values are as unusable as none.

The `/host/<name>/stream|vnc_lite` proxy locations set the same headers with `always` (so they
survive an upstream error too), hiding the upstream's copy first so exactly one is sent.

## Why it is filed separately from BUG-0101

Same investigation, two defects. BUG-0101 is why the stream was missing (the watchdog could not
see a stalled input). This one is why it took so long to find: the error that would have said
so was invisible. Fixing either alone leaves the other.
