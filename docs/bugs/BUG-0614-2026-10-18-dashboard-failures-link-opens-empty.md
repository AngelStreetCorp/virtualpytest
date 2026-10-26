# BUG-0614 — Dashboard "Failures" tile opens an empty Test Reports list

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0614                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend, backend_server                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Dashboard → Overview showed **Failures 30**; a click opened Test Reports (`?status=failed&range=7d`) with
"No script results available yet". The same happened with the passed / failed / aborted counts of the Scripts tab.

## Root cause

`getAllScriptResults` returns the latest 100 rows (on node1 that is about 3.5 hours of runs). Test Reports applied the
`status` and `range` deep-link params client-side, on those 100 rows only. The dashboard counts the whole range
server-side (195 failures over 7 days on 2026-10-18), and the few `success = false` rows inside the window were runs
still in flight, which the page shows as running, so the filtered list was empty. The Aborted count linked to the
unfiltered page.

## Fix

- `backend_server/src/routes/server_script_results_routes.py` + `shared/src/lib/database/script_results_db.py`:
  `getAllScriptResults` takes `status=passed|failed|aborted` and `range=24h|7d|30d`, applied in the query before the
  limit, without discarded runs and windowed on `created_at` like the dashboard; failed / aborted use the dashboard's own verdict (`_verdict`) and drop rows still running (`_is_running_row`).
- `frontend/src/pages/TestReports.tsx`: the deep-link params are sent to the server (limit 1000 while one is set).
- Aborted links to `status=aborted`; a per-host device row links to Device Control `?host=<host>` (`Rec.tsx` reads it);
  the per-device shortcut icons on Hosts and devices open in a new tab.
- `shared/src/lib/database/dashboard_db.py`: `get_results_since` pages past the 1000-row PostgREST response cap; the
  7 d / 30 d tiles were counting only the newest 1000 runs (7 d Failures showed 195 instead of 294 on 2026-10-18).
  The ceiling is raised from 5000 to 20000 runs: 30 d on node1 holds more than 5000 (30 d Failures showed 527 instead of 919).
- Rule: [UI_STYLE.md §16](../agent/platform/UI_STYLE.md) item 7 (a dashboard number opens filtered to what it counts).

## Verify

Open the Failures tile: the list shows the same number of rows as the tile.
