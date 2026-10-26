# BUG-0613 — Hosts and devices shows "No servers connected" under All servers

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0613                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

With "All servers" picked in the top-bar scope picker, Dashboard → Hosts and devices showed
"No servers connected", although every server was reachable.

## Root cause

`HostsDevicesView.tsx` kept only the rows whose `server_url` equals `selectedServer`. Under All
servers `selectedServer` is the `__all__` sentinel (`lib/allServer/scope.ts`), which matches no
server, so the list was always empty.

## Fix

`frontend/src/components/dashboard/HostsDevicesView.tsx`: the sentinel now means "no server
filter", so every server is listed. Each server card has a chevron on its title that folds the
card (services and hosts) away; the folded servers are remembered per browser
(`localStorage` `hostsDevices:collapsedServers`).

## Verification

Pick All servers, open Dashboard → Hosts and devices: one card per server, each with its hosts;
click a server title to fold and unfold it.
