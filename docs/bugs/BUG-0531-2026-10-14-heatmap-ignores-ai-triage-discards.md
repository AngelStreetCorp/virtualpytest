# BUG-0531 — Heatmap tiles stay red and Incidents stays high for incidents the AI triage already discarded

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0531                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / backend                                           |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/monitoring/heatmap` all 10 tiles were red at 2026-10-14 ~19:04 although most of their freeze alerts had been discarded by AI triage. The "Incidents" tile counted them too.

## Root cause

The red/green cell border and `incidents_count` are baked into the minute's mosaic and JSON by the heatmap processor from the raw frame flags, at processing time. Triage judges an alert minutes later, and the alert itself is created only after several consecutive bad frames. `get_discarded_incident_keys` (processor-side, 3-minute window) can only help for verdicts that already exist when the minute is processed, so past minutes stayed red for good.

## Fix

- `GET /server/heatmap/discardedIncidents?at=<ISO>` (`server_heatmap_routes.py`, `heatmap_db.get_discarded_incidents_at`): alerts with `discard=true` covering that instant (start up to 5 min after it, since an alert trails the first red frame; end not before it, or still open). The `alerts` table has no `team_id`, so rows are host/device/type keys that the page only matches against its own devices.
- `useHeatmap.ts`: after a frame loads, fetch the verdicts and `applyDiscards` clears the matching flags (kept in `analysis_json.discarded`) and recounts Incidents. No alert yet, or a kept alert, stays red. OK/KO filtering uses the same state.
- `MosaicPlayer.tsx`: draws the baked red border of a fully-discarded tile green again; under OK/KO with a discard in the frame the ALL mosaic is shown and tiles outside the filter are dimmed (the baked OK/KO mosaics hold the raw split). Also stopped a same-URL filter switch from sticking on "Loading mosaic…".

The mosaic images are not re-baked.

## Verification

Live data (preview of this build, auto-signed, dark and light): at 19:05–19:06 the host-clone-1 device4 tile (freeze alert discarded) turns green and Incidents drops 5 → 4; OK filter keeps both green tiles bright and dims the four reds. The new route itself was not reachable on the live server (not deployed), so the preview answered it from live `getAllAlerts` with the same rule; verify the real route after deploy.
