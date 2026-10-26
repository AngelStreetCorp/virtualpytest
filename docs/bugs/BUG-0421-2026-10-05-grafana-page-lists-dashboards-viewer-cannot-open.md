# BUG-0421 — Grafana page lists dashboards the viewer cannot open (403 "Failed to load dashboard")

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0421                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | ec5dd244d, 994515334                                         |

---

## Symptom

On a customer deployment the `/grafana-dashboard` page opened on "Server Monitoring" and showed
"Failed to load dashboard" with `status 403`. Another deployment showed "Dashboard not found" for
"labox Quality". Not reproducible with an admin account.

## Root cause

`frontend/src/pages/GrafanaDashboard.tsx` hardcoded the dashboard list and the default
(`system-monitoring`). Two problems:

- the list held dashboards that are not common to every deployment (FullZap Results; an older
  build also had labox Quality) while customers provision their own;
- every viewer got the same list and the same default, although Grafana only lets a viewer open
  the dashboards their role / folder permissions allow. Server Monitoring is about the platform's
  own server, so a customer viewer is refused (403).

The exact Grafana permission on the customer side was not inspected; the 403 is Grafana's answer
for a dashboard the user may not read.

## Fix

- Removed FullZap Results from the list; the page opens on Script Results.
- The page asks Grafana's `/api/search` (with the viewer's session) and lists only the dashboards
  the viewer can open; if the selected one is not allowed it switches to the first allowed one.
  If the search cannot be reached (Grafana on another host, no session) the full list is kept.

## Verification

`tsc --noEmit` clean. Not yet tested in a browser against the customer's Grafana: on their page run
`fetch(<grafana url>+'/api/search?type=dash-db',{credentials:'include'}).then(r=>r.status)` — 200
means the filtering applies; otherwise the server would need to ask Grafana for the viewer.
