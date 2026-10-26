# BUG-0844 — A tap on a phone's stream asks the wrong server ("Host vpt-pi1 not found")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0844                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Take Control on an Android phone on vpt-pi1, then tap on the stream: every tap failed with
`POST /server/remote/tapCoordinates` → 400 `{"error":"Host \"vpt-pi1\" not found"}`. Remote keys (DPAD, BACK…)
on the same device worked.

## Root cause

`AndroidMobileOverlay.tsx` and `AppiumOverlay.tsx` sent the tap with `buildServerUrl()`, the server selected
in the UI. vpt-pi1 is registered on its own server, not on that one, so the server did not know the host. Keys
go through `useControllerApi().postToHost()`, which already uses the host's `server_url`.

## Fix

Both overlays build the tap URL with `buildHostServerUrl(host, '/server/remote/tapCoordinates')`, the same
routing as `postToHost()`.

## Verification

Take Control on the vpt-pi1 phone and tap the stream: the request goes to the host's server and returns
`success: true`; the phone reacts.
