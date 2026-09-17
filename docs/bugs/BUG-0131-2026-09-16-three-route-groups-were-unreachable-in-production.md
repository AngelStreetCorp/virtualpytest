# BUG-0131 — The whole events API was dead in production, and a test marker was hiding it

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0131                                                                    |
| Reported  | 2026-09-16                                                                  |
| Status    | Fixed (pending deploy)                                                      |
| Severity  | High (an alert POST returned 200 and was never delivered; the same routes were also ungated) |
| Area      | `backend_server/src/routes/` — event, frontend-control and OpenAPI blueprints |
| Fixed in  | build 9151                                                                  |
| Commit    | `TBD`                                                                       |

---

## Symptom

`POST /api/events/alerts/blackscreen` — and every other route in three blueprints — answered
**HTTP 200 with the frontend's `index.html`** on the public deployment, for any path and any
method. A caller checking the status code saw success and moved on; no event was ever published,
routed or logged.

Nothing alerted, because nothing failed. The twelve tests that would have caught it were marked
`local_only` and deselected in CI, so the routes were reported on by nobody.

## Root cause

nginx (`infra/proxy/nginx/config/production-https.conf`) proxies only `/server/*` to
backend_server. Three blueprints were mounted outside it:

| blueprint | old prefix | what happened |
|---|---|---|
| `server_event_bp` | `/api/events` | no `/api/` location block at all → `location /` catch-all → SPA |
| `server_frontend_bp` | *(none — server root)* | `/navigate` → SPA; `/health` matched nginx's **own** `location /health` (`return 200 "healthy"`), so the handler was unreachable even in principle |
| `server_openapi_bp` | `/docs/api` | not proxied, **and** shadowed by the frontend's published docs site (`frontend/public/docs/api`, Swagger UI at `/docs/api/interactive.html`) |

`app.py`'s frontend JWT guard also keys on paths starting with `/server/`, so all three were
outside authentication as well — `/api/events/publish` would have been an unauthenticated write
endpoint had it been reachable.

When the non-regression backfill found these unreachable in September, the tests were marked
`local_only` and deselected rather than the mounts being questioned. The marker recorded the
symptom as if it were a property of the tests. It was a platform defect.

## Fix

The blueprints move under `/server/*`, matching every other backend blueprint:

| blueprint | new prefix |
|---|---|
| `server_event_bp` | `/server/events` |
| `server_frontend_bp` | `/server/frontend` |
| `server_openapi_bp` | `/server/docs/api` |

Nothing called the old paths — verified across the repo, the frontend bundle and the fleet — so
no caller had to change. The routes are now proxied, collide with no nginx block, and are covered
by the JWT guard.

The `local_only` marker is deleted outright: its registration in `tests/backend_server/conftest.py`,
its uses in `test_events.py` / `test_frontend_routes.py` / `test_openapi.py`, and the
`and not local_only` half of the CI marker expression in `.github/workflows/regression.yml`. Those
twelve tests now run on every push like any other.

## Verification

Collection count rises from 598 to 610 selected, 11 deselected (`manual` only). Against the
deployed server, the routes answer as routes rather than as HTML:

```
POST /server/events/publish          -> 201 {"event_id":"evt_…","routed":false}
POST /server/events/alerts/blackscreen (no device_id) -> 400 {"error":"device_id required"}
POST /server/frontend/navigate       -> 400 {"error":"No JSON data provided"}
GET  /server/docs/api/docs/__nope__  -> 404
```

## Why it is filed as a bug and not a chore

The events API is a delivery path: blackscreen and device-offline alerts, build-deployed
notifications. It has been accepting writes and discarding them for as long as the public
deployment has existed. A route that returns 200 while doing nothing is worse than one that
returns 502.
