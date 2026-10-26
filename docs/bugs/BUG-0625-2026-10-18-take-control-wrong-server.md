# BUG-0625 — Take Control fails with "Host not found" when all servers are selected

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                |
|-----------|----------------------|
| ID        | BUG-0625             |
| Reported  | 2026-10-18           |
| Status    | Fixed (pending deploy) |
| Severity  | Medium               |
| Area      | frontend             |
| Fixed in  | build 90145 |
| Commit    | TBD                  |

---

## Symptom

With the server picker on "All servers", Take Control on a host owned by another server (e.g. `vpt-pi1`)
returned `404 {"error":"Host vpt-pi1 not found","errorType":"device_not_found"}` from `/server/control/takeControl`.

## Root cause

`HostManagerProvider.takeControl` / `releaseControl` posted to `buildServerUrl()`, which in "All servers" mode is the
default (primary) server. Each server has its own host registry, so the primary did not know the host.

## Fix

`frontend/src/contexts/HostManagerProvider.tsx`: both calls go to the host's own `server_url` (stamped by
`ServerManagerProvider`) via `buildServerUrlForServer`, falling back to the selected server when absent.

## Verification

After deploy: All servers selected, Take Control on a `vpt-pi1` device succeeds.
