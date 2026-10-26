# BUG-0479 — Group control of phones: remote panel clicks tap the phone instead

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0479                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend · device control · group control (TASK-76)          |
| Fixed in  | build 90145 |
| Commit    | 06c3a6ab2                                                    |

---

## Symptom

On `/device-control`, a group-control tile of Android phones (e.g. S21x + S7) showed the Android
Mobile remote on the right, but most clicks on it did nothing useful: the App Launcher stayed at
"0 apps" after Refresh Apps, the app list never offered YouTube, and the first phone of the group
opened random apps (a weather page) by itself. A crosshair cursor and a coordinate tooltip
(`532, 256`) appeared over the remote panel.

## Root cause

`GroupRemoteSide` passes the remote's own box as `streamContainerDimensions` so `RemotePanel`
lays itself out inline. `AndroidMobileRemote` uses those same dimensions to position its tap
overlay (`AndroidMobileOverlay`, portalled to `document.body`, z-index 300). In the group tile
there is no single stream, so the overlay landed exactly on top of the remote panel and every
click on a panel control became a `tapCoordinates` call to the primary phone.

## Fix

`GroupRemoteSide` renders `RemotePanel` with `showOverlay={false}`: the group tile has one stream
cell per member and no stream the overlay could align with. Single-device control is unchanged.

## Verification

Local build of the branch against the rpitest server, S21x (vpt-pi1 device1) + S7 (vpt-mf1
device6) in one group: before the fix `document.elementFromPoint` on the App Launcher returned the
z-300 overlay div; after, no overlay exists, Refresh Apps lists 60 apps, launching an app, HOME,
BACK, Click by Text, the new key row and Type text all reach both phones with a per-cell "Sent".
