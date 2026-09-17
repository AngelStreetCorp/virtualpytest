# BUG-0103 — Cross-server stream URLs keep a stray `host/` segment and silently load the SPA

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0103                                                                    |
| Reported  | 2026-09-15 (QualiAI server on `virtualpytest.angelstreet.io`, still failing after BUG-0100) |
| Description | Regression introduced by the BUG-0100 fix                                 |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (every cross-server stream stays on "Loading stream…", and the failure is invisible — the request succeeds) |
| Area      | `frontend/src/utils/buildUrlUtils.ts` — `internalBuildHostUrl()`             |
| Fixed in  | build 9151                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

With BUG-0100 deployed, QualiAI hosts selected from the main frontend *stopped* 502ing and
instead sat on "Loading stream…" indefinitely, with nothing in the console — no 404, no CORS
complaint, no hls.js error the user would notice.

## Cause

`internalBuildHostUrl()` strips the redundant `host/` prefix from the endpoint when the host's
URL is already a `/host/<name>` proxy path:

```ts
if (hostUrl.startsWith('/host/') && finalEndpoint.startsWith('host/')) {
  finalEndpoint = finalEndpoint.slice('host/'.length);
}
```

BUG-0100 made `hostUrl` the *resolved* URL, which for another server is now
`https://virtualpytest.qualiai.io/host/host-android-mobile` — no longer starting with `/host/`.
The check silently stopped firing for exactly the case the prefixing was added to fix, leaving
the `host/` segment in place:

```
https://virtualpytest.qualiai.io/host/host-android-mobile/host/stream/capture1/segments/output.m3u8
                                                          ^^^^^
```

**And that URL answers `200`.** It matches no `/host/<name>/stream/` location, so it falls
through to the SPA catch-all and returns `index.html`. hls.js is handed HTML where it expects
`#EXTM3U`, and a manifest parse failure on a live stream just… keeps loading. A 404 would have
been louder.

```
$ curl .../host/host-android-mobile/host/stream/capture1/segments/output.m3u8
<!doctype html><html lang="en"> …                ← the SPA

$ curl .../host/host-android-mobile/stream/capture1/segments/output.m3u8
#EXTM3U                                          ← the manifest
```

## Fix

Test the host's **registered path** (`host.host_url`, always the relative `/host/<name>` the host
registered) rather than the resolved URL. The dedup then fires identically whether or not an
origin was prefixed. Same-origin hosts, absolute `host_url`s, VNC endpoints and hosts cached
before BUG-0100 (no `server_url`) all produce byte-identical URLs to before.
