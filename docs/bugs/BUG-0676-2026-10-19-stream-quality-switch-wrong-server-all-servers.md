# BUG-0676 — Switching stream quality failed with "Host not found" for a device owned by another server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0676                                                                                       |
| Reported  | 2026-10-19                                                                                     |
| Status    | Fixed (pending deploy)                                                                         |
| Severity  | Medium (LOW / SD / HD could not be switched for any device whose host registers on a peer server) |
| Area      | `frontend/src/hooks/rec/useRecQualitySwitch.ts`, `frontend/src/hooks/rec/useQualitySelection.ts` |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                                            |

---

## Symptom

In the device stream modal, clicking SD (or HD) showed the toast "Failed to switch to SD quality"
while the video kept playing. The network tab showed:

```
POST <primary server>/server/system/setStreamQuality  ->  404  {"error":"Host <name> not found","success":false}
```

The stream itself loaded from the peer server's own domain, so only the quality calls failed. The
quality toggle also could not read the stream's current quality (`getStreamQuality` 404).

## Root cause

The device is listed from a peer server (every backend server keeps its own host registry; the
"All servers" scope shows all of them in one grid). The quality hooks built their URLs with
`buildServerUrl()`, which resolves to the *selected* server and, in "All servers" scope, to the
default server. That server does not know the peer's host, so the proxy route
(`server_system_routes.py` `setStreamQuality`) answers 404 "Host not found" before any host is
called. The helper `buildHostServerUrl(host, …)` exists for exactly this and was already used by the
stream player; the two quality hooks were never moved to it.

## Fix

`useRecQualitySwitch` (current-quality read, the switch, and its retry) and `useQualitySelection`
(current-quality read and the bulk switch) now call `buildHostServerUrl(host, …)`, so the request
goes to the server that owns the host.

## Verification

Before: in "All servers" scope, open a stream tile of a host that registers on a peer server; the
console shows `getStreamQuality?host_name=<peer host>` going to the primary server, answered `404`
"Host <peer host> not found".

After deploy: the same request goes to the owning server and answers `200` with the quality; the
SD / HD toggle switches and the stream restarts in the new quality.
