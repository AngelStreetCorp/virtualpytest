# BUG-0952 — A VNC tile used another server's password for a host with the same name

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0952                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

On the Device page in All-servers mode, `host-clone-1` from node1 and `host-clone-1` from QualiAI
(different machines with the same name) showed side by side. The QualiAI tile's iframe URL carried
two `password=` parameters, one of them node1's host password. A host whose password differs from
its namesake's would get "Something went wrong, connection is closed": TigerVNC refuses the wrong
password, and after a few refusals it blacklists 127.0.0.1, which every websockify connection
comes from, so all tiles of that host fail.

## Root cause

`useVncPassword` (`frontend/src/hooks/controller/useVncPassword.ts`) caches the password answered by
`/server/system/vnc-info` for the whole page load, keyed by `host_name` only. Whichever server
answered first filled the cache for every host of that name.

## Fix

The cache key is `<server_url>|<host_name>`, so each server's host gets its own lookup.

## Verification

All-servers mode, PC filter: both `host-clone-1` tiles and both `host-clone-2` tiles connect, and
each iframe URL carries one `password=` parameter.
