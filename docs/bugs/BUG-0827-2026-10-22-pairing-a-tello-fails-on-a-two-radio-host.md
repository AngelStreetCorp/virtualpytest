# BUG-0827 — Pairing a Tello fails on a host with one Wi-Fi dongle per drone

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0827                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host (host_drone_routes.py)                          |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On vpt-pi4 (two dongles, one per Tello) the Device tile says "drone found" but pairing
TELLO-C5B142 fails, and a paired drone never shows as connected.

## Root cause

`/host/drone/tello/pair` joins with `nmcli device wifi connect` and reads the association from
`nmcli con show --active`. On a two-radio host `tello_prio.sh` keeps each dongle out of
NetworkManager, so nmcli joins the wrong radio (or none) and never reports the association.

## Fix

`backend_host/src/routes/host_drone_routes.py`: a slot with its own `DEVICE<i>_TELLO_LOCAL_IP`
joins its radio through `tello_prio.sh up` (radio and drone number read back from the kernel's policy
rules) and reads the association with `iw`. Other hosts keep the nmcli path. New sudoers rule in
`setup/local/linux/backend_host/sudoers.d/tello-wifi`, installed on vpt-pi4.

## Verification

Pair each drone from the Device tile on vpt-pi4; the tile shows connected.
