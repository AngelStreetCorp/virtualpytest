# BUG-0100 — Streams and VNC of a host on another server load against the wrong proxy (502)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0100                                                                    |
| Reported  | 2026-09-15 (QualiAI server selected on `virtualpytest.angelstreet.io`)       |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (every stream/VNC/capture of a non-primary server is unreachable; worse, a host name that exists on both servers silently loads the *other* machine) |
| Area      | `frontend/src/utils/buildUrlUtils.ts` · `frontend/src/contexts/ServerManagerProvider.tsx` · `frontend/src/types/common/Host_Types.ts` |
| Fixed in  | build 9151                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

With **Server: QualiAI** selected in the server picker on `virtualpytest.angelstreet.io`, every
device tile sits on "Loading stream…" and the console shows:

```
GET https://virtualpytest.angelstreet.io/host/host-android-mobile/stream/capture1/segments/output.m3u8 502 (Bad Gateway)
GET https://virtualpytest.angelstreet.io/host/host-android-tablet/stream/capture1/segments/output.m3u8 502 (Bad Gateway)
GET https://virtualpytest.angelstreet.io/host/host-android-tv/stream/capture1/segments/output.m3u8   502 (Bad Gateway)
```

Those hosts live on **proxmox3** and are reachable at `virtualpytest.qualiai.io`. The browser asked
the *main* proxy for them.

## Cause

A host registers a **relative** `host_url`, e.g.

```
host-android-mobile   host_url='/host/host-android-mobile'   host_api_url='http://192.168.0.180:6109'
```

which is correct as long as the frontend and that host's proxy are the same origin.
`internalBuildHostUrl()` concatenates `host_url` with the endpoint and hands the result to the
browser, which resolves the leading `/` against **the page's** origin. With more than one server in
`VITE_SLAVE_SERVER_URL` that assumption breaks: selecting another server keeps building URLs
against the frontend's own proxy.

Verified against the main proxy:

| path | result |
|---|---|
| `/host/host-android-mobile/stream/capture1/segments/output.m3u8` | 502 |
| `/host/host-android-tv/stream/capture1/segments/output.m3u8` | 502 |
| `/host/host-clone-2/stream/capture1/segments/output.m3u8` | 502 |

The third one is the dangerous case: `host-clone-2` exists on **both** nodes, so the URL is not
merely broken — when that upstream is up it resolves to the main node's host-clone-2 while the UI
says you are looking at QualiAI's.

## Fix

`ServerManagerProvider` already fetches per server, so it stamps each host with the server it came
from (`server_url`, the public base URL from `VITE_SERVER_URL` / `VITE_SLAVE_SERVER_URL`).
`buildUrlUtils` gains `resolveHostUrlOrigin()`: a relative `host_url` is prefixed with that
server's origin when it differs from the page's. Same-origin hosts and absolute `host_url`s are
untouched, so single-server deployments behave exactly as before. Every consumer —
`buildStreamUrl` (HLS **and** VNC), `buildHostUrl`, `buildCaptureUrl`, `buildHostImageUrl` — goes
through `internalBuildHostUrl`, so one change covers them all.

## Not this bug

Two things found while chasing it that are *not* caused by it:

- **`vpt-pi1` / `S21x` (device1) has no stream at all** — no `hot/segments/output.m3u8`, public URL
  404s, and its ffmpeg is still logging while its frame counter is frozen at `frame=2441384`
  (~67 h of runtime): a wedged capture input, not a URL problem.
- **A 404 on a stream manifest surfaces in the browser as a CORS error**, because nginx does not
  add `Access-Control-Allow-Origin` to error responses (`add_header … always` is missing). The
  cross-origin caller sees "blocked by CORS policy" and the real status is invisible.
