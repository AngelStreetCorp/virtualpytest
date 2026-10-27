# BUG-0956 — A device's profile badge kept its old value after the host changed it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0956                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90256 |
| Commit    | TBD                                                          |

---

## Symptom

`DEVICE5_MONITOR_PROFILE=drone` was set on host-clone-1 and `/server/system/getAllHosts` answered
`monitor_profiles.device5 = drone`. A browser that had opened the Device page before the change
still showed "PC" on the "Tello via phone" tile, and its tooltip still said `tello - pc`, after a
page reload. A fresh browser profile showed "Drone".

## Root cause

`preserveRicherStats` (`frontend/src/contexts/ServerManagerProvider.tsx`) merges each host-list
refresh with the previous one, so a lightweight round (`include_system_stats=false`) does not blank
the Dashboard gauges. When the previous host had `system_stats`, it replaced the new host's
`system_stats` whole. The previous copy is seeded from the localStorage host cache on page load, so
the fields a lightweight round does return (`monitor_profiles`, `monitoring_off`, …) were thrown
away on every refresh, and the cached values from an earlier visit stayed on screen.

A second layer kept it too: `HostManagerProvider` keeps its previous host objects unless the host
name, status, device list, `last_seen` or `operational_status` changed. A changed
`monitor_profiles` alone was not a change, so the tiles kept reading the old host object.
A third layer did the same on the Device page: `useRec` keeps its (host, device) list unless its
signature (device ids and running deployments) changes.

## Fix

The host's `system_stats` is now `{ ...previous, ...this round }`: fields from this round win, and
fields only a full round carries are kept from the previous one. `HostManagerProvider` also treats
a changed `system_stats.monitor_profiles` as a host change, and `useRec` puts each device's profile
in its signature.

## Verification

In a browser that had the Device page open before the change, reload: the "Tello via phone" tile
reads "Drone" and its tooltip `tello - drone`.
