# BUG-0276 — Atlas analytics failed on every question asked through the Pi-hosted server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0276                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — the analytics layer did not work at all on that server |
| Area      | `backend_server/src/lib/analytics/service.py`, `backend_server/src/routes/server_atlas_analytics_routes.py`, `backend_server/src/lib/auth_middleware.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `47d971fc9`, `06aa2cbd5`, `510bd4281`, `d801d2147`, `927441c13`, `61bfab990` |

---

## Symptom

In Agent Chat with the Pi-hosted backend server selected, "show failing testcases for this
device" failed with *Tool 'render_analytics_artifact' encountered an error: Analytics datasource
is not configured*; every other analytics question failed the same way. After the first fix the
same questions failed with *Analytics query failed.*, and "only regressions over 10%" answered
"no regressions" from a comparison on a text field.

## Root cause

- Analytics runs read-only SQL over a direct Postgres connection (`ANALYTICS_DB_URI` /
  `SUPABASE_DB_URI`). The Pi-hosted server sits on another network and reaches the database only
  through the Supabase API; it has no such connection and cannot open one.
- The first fix forwarded the query to the primary server, whose route re-checked the team
  against the user's memberships. The auto-sign test login is the shared principal `auto_sign`,
  which has no membership rows, so it was refused (403) and the refusal surfaced as the generic
  failure.
- A comparison accepted any field present in the result as its metric, including `variant`.
- The live smoke test before this only went through the primary server, so none of this showed.

## Fix

- A server without a datasource forwards the database half — the compiled query and the
  non-admin live-status device scope — to the primary server's service-key-only
  `/server/atlas-analytics/{query,device-scope}` routes (target `ANALYTICS_FORWARD_URL`, else the
  origin serving `SUPABASE_URL`). The routes re-check a person's team, accept shared principals
  as the socket handler does, and refuse to forward again. Rendering, comparison, export and
  "this device" resolution stay on the forwarding server.
- 400/403 reasons from the primary server reach the chat instead of the generic failure.
- A comparison metric must be a numeric metric distinct from `align_by` and `series_field`.

## Verification

- `tests/backend_server/test_atlas_analytics_forwarding.py` (config from env, forwarding with
  local device resolution, service-key-only routes, team re-check incl. shared principals, no
  forwarding loop, end to end through the real route) and the comparison metric test.
- Live on build 9675, through **both** the primary and the Pi-hosted server, every smoke prompt
  answered correctly: failing testcases for the selected device, pass rate by device, degraded
  hosts, KPI radar, a 3-panel canvas for two devices, a real CSV export and a Grafana draft.
  "Only regressions over 10%" returned exactly the 5 regressions the database shows in 4 of 4
  runs (it had been 1, 4 or a speed-up mis-read as a regression before the follow-up fixes:
  comparison metric must be numeric, direction comes from the metric, two variants are
  compared automatically, one-sided rows are counted separately).
