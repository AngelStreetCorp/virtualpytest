# BUG-0636 — vpt-pi4 tiles poll the wrong server: 400 "Host not found"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0636                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On Device Control with "All servers" selected, the browser console fills with 400s for devices of
vpt-pi4 (which runs its own server):

- `GET /server/drone/tello/status?host_name=vpt-pi4&device_id=device3` (the Tello tile)
- `POST /server/monitoring/latest-json` (the Localize badge on every vpt-pi4 tile), every 1-3 s

Both answer `{"error":"Host \"vpt-pi4\" not found"}`: the request reaches
the main server, whose registry does not know vpt-pi4. The same calls sent to
vpt-pi4's own server answer 200. The Tello tile stays on "Rescan" because its status poll fails.

## Root cause

`useDroneWifiStatus` (status, scan, pair) and `LocalizeVideoBadge` built their URLs with
`buildServerUrl()`, which targets the selected/primary server, instead of the server that owns the
host (`host.server_url`). `HostManagerProvider` already had a private `buildHostServerUrl` for this.

## Fix

`buildHostServerUrl(host, endpoint)` moved to `frontend/src/utils/buildUrlUtils.ts` and is used by
`HostManagerProvider`, `useDroneWifiStatus` and `LocalizeVideoBadge`.

## Verification

Device Control in "All servers": no 400 on `tello/status` or `latest-json` for vpt-pi4 devices in
the network tab; the requests go to vpt-pi4's own server.
