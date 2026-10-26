# BUG-0381 — Atlas Grafana draft links opened a 404 on the marketing website

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0381                                                       |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                           |
| Area      | backend + frontend                                                   |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

Found by the live post-deploy suite (TASK-43 phases 9/10, build 9965/9966): the "Open in Grafana" link on a canvas and the link in a dashboard answer were `https://www.virtualpytest.com/grafana/d/atlas-draft-…` and returned 404, while `https://virtualpytest.angelstreet.io/grafana/d/<uid>` returned 200.

## Root cause

`grafana_push.public_base()` built the link from `GRAFANA_DOMAIN`. On the main server that variable is the marketing website (it is also used for user mirroring), not the host that serves Grafana. The server cannot know the public Grafana host; the web app does (`VITE_GRAFANA_URL`, used by every other Grafana link).

## Fix

The server now returns a host-independent path (`dashboard_path`: `/grafana/d/<uid>?var-workspace=<id>`) and never reads `GRAFANA_DOMAIN`. The canvas link is resolved in the browser by `resolveGrafanaPath` (`frontend/src/utils/grafanaUrl.ts`: `VITE_GRAFANA_URL` + path without `/grafana`, the same rule as the `/grafana` redirect route). For the answer text the frontend sends `grafana_base_url` (its `VITE_GRAFANA_URL`) in the `send_message` context; the server accepts it only as a plain http(s) URL (`clean_grafana_base`: no credentials, query, fragment or odd characters), keeps it in the session context and uses it only to write the link text (`absolute_url`). Without it the answer carries the same-origin `/grafana/...` path. A Pi server forwards the push to main and returns the same path, and its chat sends the same app base, so Pi links open main's Grafana.

## Verification

`tests/backend_server/test_atlas_grafana_push.py` (main case with `GRAFANA_DOMAIN=www.virtualpytest.com`, Pi case, hostile bases rejected), `tests/frontend/AnalyticsArtifactViewer.test.tsx`, `analyticsExport.test.ts`, `GrafanaRedirect.test.tsx`. After deploy the live suite's canvas link check fetches the link and must see HTTP 200 (it fails on 404 until then).
