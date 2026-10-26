# Grafana Dashboards

Exported Grafana dashboards (JSON) for VirtualPyTest. Import them into any Grafana
instance backed by the VirtualPyTest Postgres/Supabase schema.

## Device scope — every dashboard shows the viewer only their devices

Each dashboard (all but `system-server-monitoring.json` and `system-service-status.json`, which are about
the platform's own server and VMs) starts
with two variables:

- **Workspace** — a visible drop-down: "None" plus the viewer's workspaces,
  `grafana_user_workspaces('${__user.email}', '${__user.login}')` — every workspace for a
  VirtualPyTest admin and for Grafana's built-in `admin` login. Links from the app pass the active
  one (`var-workspace=<id>`).
- **allowed_devices** — hidden. `grafana_device_scope('${__user.email}', '${__user.login}', '${workspace}')`
  returns the devices the viewer's team, role and user limits (and the chosen workspace) allow,
  matched by **email** to the VirtualPyTest account. `*` = everything (VirtualPyTest admins and
  Grafana's built-in `admin`), `-` = nothing (no VirtualPyTest account).

Every read of a device table is wrapped as `(SELECT * FROM <table> /*device-scope*/ WHERE …) alias`.
**Never write a device-table query by hand without it** — run the transform instead:

```bash
python3 _apply_device_scope.py          # adds the variables and wraps every read (idempotent);
                                        # covers this folder and features/*/grafana/*.json
python3 _check_device_scope.py          # fails on any unscoped read; pinned by
                                        # tests/backend_server/test_dashboard_device_scope.py
```

This filters what dashboards show; it is not authorization (one shared DB login). Only admins are
Grafana Editors, so nobody else can edit a panel's query. Needs migration
`setup/db/migrations/20260929f_grafana_device_scope.sql` on the database.

## The house shape — every dashboard ends with a collapsed "Details" section

A dashboard opens on its overview; the detail tables live in a row at the bottom
that is **collapsed by default**. The reference is `script-results.json`:
`Overview` (open) → `Main` (open) → `Details` (collapsed, its panels nested
inside the row).

Every dashboard in the repo follows it — this folder and each feature's
`grafana/` folder:

```bash
python3 _apply_details_row.py      # brings every dashboard to the house shape (idempotent)
python3 _check_details_row.py      # fails on a dashboard that does not end with a collapsed "Details"
```

`_apply_details_row.py` collapses the last row of a dashboard that has rows
(the panels that follow it move inside the row) and renames it to "Details",
keeping the old title in the row's `description`. A dashboard without rows is
split in two: the leading panels become an "Overview" row, the rest become the
collapsed "Details" row, split at the first table panel.

## `template.json` — not a dashboard

The house style Atlas starts generated dashboards from (variables, time, styling, grid, example query patterns; contract in its `description`, details in `docs/agent/ai/ATLAS_ANALYTICS.md`). The backend reads it from this path; a customer overlay that ships its own `template.json` replaces it. It is never pushed (`_push_dashboard.py` skips it) and the device-scope tools ignore it.

## Dashboards

**Test execution & results**
- `home-dashboard.json` — one page for the checks worth watching: a sanity table over a fixed script list, then one collapsed row per script (Ookla, Superping, DNS, Facebook, YouTube)
- `script-results.json` — script run history, success rate, durations
- `campaign-results.json` — campaign run results
- `fullzap-results.json` — full zapping campaign results
- `all-zapping-events.json` — individual zap events (zap duration, blackscreen/freeze, audio silence)
- `kpi-measurement.json` — navigation KPI measurements per action set
- `navigation-metrics.json` — navigation node/edge execution metrics
- `device-information-get-info.json` — device inventory from `get_info` (model, firmware, versions)
- `game-2048.json` — 2048 showcase (TASK-33, script `game/game_2048`): score, max tile, speed and pass rate per platform and player, plus a table of runs with report links
- `image-telemetry.json` — image telemetry (TASK-157): frames per second the img monitor sees, JPEG throughput, frame age p95, drops, monitor and ffmpeg CPU/RSS, load per core, from `image_telemetry_buckets` (60 s buckets, 7 days). Hand-built, device-scoped like the others (the `_host` row is widened in the host variable and process panels). Push: `GRAFANA_PASS=<admin password> python3 _push_dashboard.py image-telemetry.json` — `GRAFANA_PASS` is required, there is no default and the repo does not hold it.
- `av-check-results.json` — `av_check` (TASK-138): is the device really playing sound and video? Run overview and pass rate, the verdict split over time (PASS / VIDEO / AUDIO / NAVIGATION / SCRIPT ERROR, read from each run's own error message), pass rate per device, the per-device table, the failure reasons and the recent runs with a link to each run's report. Regenerate with `python3 _gen_av_check_dashboard.py` (the generator and `_apply_device_scope.py` agree on the file, so re-running either changes nothing) and check the panel SQL with `GRAFANA_URL=… GRAFANA_USER=… GRAFANA_PASS=… python3 _check_panel_sql.py av-check-results.json` before a push

**Network / gateway tests**
- `dns-lookup.json` — DNS resolution time
- `ookla-speedtest.json` — Ookla speedtest (download/upload/latency)
- `superping.json` — ping/network quality (latency, jitter, packet loss)

**System monitoring**
- `system-host-monitoring.json` — per-host CPU / memory / disk / services
- `system-server-monitoring.json` — backend server metrics
- `system-service-status.json` — the `/status` page as history: server services, Supabase, Redis, DB backup and every infra VM (CPU / RAM / disk + its services) via the [VM agent](../../vm_agent/README.md); needs migrations `setup/db/migrations/20261001e_infra_status.sql` + `20261001f_infra_status_compact.sql`
- `device-alerts-dashboard.json` — device alert overview

**Operations**
- `deployment-table.json` — deployment history
- `discard-scripts-reviewed.json` — review queue for discarded script runs
- `discard-incidents-reviewed.json` — review queue for discarded incidents

**CI/CD (separate datasource `cicd-postgres`, schema `cicd` — see `features/cicd/db/`)**
- `cicd-quality.json` — white-box / grey-box CI results of every project: run & job pass rates, per-layer trend, jobs table with last result + pass % in range, runs table with report links

**Platform**
- `virtualpytest-self-test.json` — internal quality dashboard: testcase/requirement/coverage health, execution timeline, success/fail breakdown

**Per-project quality** — one per AngelStreet project, generated by `../_gen_project_dashboard.py` (same look/panel set as the Self-Test dashboard, scoped to the project's `userinterface_name` surfaces). **These live in the root Grafana folder `apps`** (uid `ffx4c203yicxsb`), not in `VirtualPyTest` — push with `GRAFANA_FOLDER=apps python3 _push_dashboard.py <app>-quality.json`.
- `sample-app-quality.json` (uid `sample-app-quality`) — sample-app black-box health across `sample-app_tv` / `sample-app_mobile` / `sample-app_tablet` / `sample-app_web`: pass rate 7d/30d, last-run tile per surface, pass-fail and duration trends, run timeline per script, campaign executions, per-script summary and the last 30 runs with clickable HTML report links. Regenerate with:
  `python3 ../_gen_project_dashboard.py --project sample-app --surface tv=sample-app_tv --surface mobile=sample-app_mobile --surface tablet=sample-app_tablet --surface web=sample-app_web --campaign-prefix sample-app_`

## Import

**Grafana UI:** Dashboards → New → Import → upload the JSON (or paste it) → pick a folder → set the datasource → Import.

**API:**
```bash
curl -X POST http://your-grafana/api/dashboards/db \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d @dashboard-filename.json
```

Notes:
- Update datasource UIDs (e.g. `supabase-postgres`) to match your Grafana instance.
- `overwrite` is `false` by default to avoid clobbering existing dashboards.
- `_push_dashboard.py` pushes a dashboard JSON to Grafana via the API.

## Gateway filters (network dashboards)

`dns-lookup.json`, `ookla-speedtest.json`, and `superping.json` can filter their
data by gateway attributes (technology, network type, model, firmware, MAC) even though
those scripts don't collect that metadata themselves. Each panel wraps its query in an
`enriched_results` CTE that attaches the host's gateway facts from `gw_info_latest`, the
trigger-maintained table of the latest auth-successful `gw_info` scan per host
(`setup/db/migrations/20260910c_gw_info_latest.sql`):

```sql
WITH gw AS (
  SELECT DISTINCT ON (host_name) host_name,
    COALESCE(technology, 'Unknown')       as gw_technology,
    COALESCE(network_type, 'Unknown')     as gw_network_type,
    COALESCE(modem_name, 'Unknown')       as gw_model,
    COALESCE(firmware_version, 'Unknown') as gw_firmware,
    COALESCE(hgw_mac, 'Unknown')          as gw_mac
  FROM gw_info_latest
  ORDER BY host_name, started_at DESC
),
enriched_results AS (
  SELECT sr.*,
    COALESCE(gw.gw_technology, 'Unknown') as gw_technology,
    -- ... one column per fact ...
  FROM script_results sr
  LEFT JOIN gw ON gw.host_name = sr.host_name
  WHERE sr.script_name = 'superping'
)
```

Then each panel appends, as needed:

```sql
AND ('${technology:csv}' = '' OR gw_technology = ANY(string_to_array('${technology:csv}', ',')) OR gw_technology = 'Unknown')
AND ('${model:csv}'      = '' OR gw_model      = ANY(string_to_array('${model:csv}', ','))      OR gw_model = 'Unknown')
-- same for gw_network_type / gw_firmware / gw_mac
```

A host with no auth-successful scan reads `Unknown` and passes every gateway filter, so
filtering never hides a host for lack of gateway data. The template variables read
`gw_info_values` (every value ever seen per kind), not `script_results`.

**Do not attach the gateway facts per result row** (a `LEFT JOIN LATERAL ... ORDER BY
started_at DESC LIMIT 1` against `gw_info` for each row). It is fast on a small DB and
collapses on a large one: on a 1.7M-row production DB with `gw_info` running every 40
minutes it cost 57K index probes plus a metadata fetch each per 7-day panel load, and a
range-join rewrite of it cost a 16.8M-row join. The 19-row join above is the pattern.
See `docs/agent/infra/GRAFANA_DASHBOARD_PERF.md`.

To add gateway filters to another dashboard: copy the five `technology`/`network`/`model`/
`firmware`/`mac` template variables from one of the above, prepend the two CTEs to each query,
and append the filter clauses.
