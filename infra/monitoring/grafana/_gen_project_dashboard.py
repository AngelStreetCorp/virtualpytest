#!/usr/bin/env python3
"""Generate a per-project Grafana quality dashboard.

Every AngelStreet project (sample-app, ...) gets a dashboard modelled on the
"VirtualPyTest Self-Test" dashboard (uid `vpt-self-test`): same datasource,
same panel styling, same row layout — but scoped to the project's own
`userinterface_name` surfaces instead of a single hardcoded UI.

Usage
-----
    python3 _gen_project_dashboard.py \
        --project sample-app \
        --surface tv=sample-app_tv \
        --surface mobile=sample-app_mobile \
        --surface tablet=sample-app_tablet \
        --surface web=sample-app_web \
        --campaign-prefix sample-app_

Writes `dashboards/<project>-quality.json` (bare model, no `dashboard`
wrapper — the format `_push_dashboard.py` expects) with:
  uid   = <project>-quality
  title = "<Project> Quality"

Panels: pass rate 7d/30d, last-run status tile per surface (green/red),
pass/fail + duration trends, a per-script state timeline, the latest
campaign executions, a per-script summary and the last 30 runs with a
clickable `html_report_r2_url` report link.

Then push it live (file provisioning is disabled on VM 106):
    GRAFANA_FOLDER=apps python3 dashboards/_push_dashboard.py dashboards/sample-app-quality.json
    # app dashboards live in the root Grafana folder `apps` (owner decision 2026-09-03)
"""

import argparse
import json
import os

# Reuse the Self-Test dashboard's datasource so the two look like siblings.
DS = {"type": "grafana-postgresql-datasource", "uid": "supabase-postgres"}
TEAM_ID = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"

# Surfaces come from a multi-select template variable; Grafana's SQL datasource
# quotes multi-value variables, so `IN ($surface)` expands to IN ('a','b').
SURF = "userinterface_name IN ($surface)"
HOST = "host_name IN ($host)"
SCOPE = f"team_id='{TEAM_ID}' AND {SURF}"

PASS_FAIL_MAPPINGS = [
    {"type": "value", "options": {"PASS": {"color": "green", "index": 0, "text": "✅ PASS"}}},
    {"type": "value", "options": {"FAIL": {"color": "red", "index": 1, "text": "❌ FAIL"}}},
]


# --------------------------------------------------------------------------- helpers

def target(sql, fmt="table"):
    return {
        "datasource": DS,
        "editorMode": "code",
        "format": fmt,
        "rawQuery": True,
        "rawSql": sql,
        "refId": "A",
    }


def row(title, y, pid):
    return {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "id": pid,
        "panels": [],
        "title": title,
        "type": "row",
    }


def stat(title, sql, x, y, w, h, pid, unit="short", color="blue",
         steps=None, color_mode="value", graph_mode="area", text_mode="auto",
         mappings=None, fields="", description=None):
    defaults = {
        "mappings": mappings or [],
        "thresholds": {"mode": "absolute", "steps": steps or [{"color": color, "value": 0}]},
        "unit": unit,
    }
    if steps is None:
        defaults["color"] = {"fixedColor": color, "mode": "fixed"}
    if unit == "percent":
        defaults["min"] = 0
        defaults["max"] = 100
    p = {
        "datasource": DS,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": {
            "colorMode": color_mode,
            "graphMode": graph_mode,
            "justifyMode": "auto",
            "orientation": "auto",
            "percentChangeColorMode": "standard",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": fields, "values": False},
            "showPercentChange": False,
            "textMode": text_mode,
            "wideLayout": True,
        },
        "pluginVersion": "12.3.2",
        "targets": [target(sql)],
        "title": title,
        "type": "stat",
    }
    if description:
        p["description"] = description
    return p


def timeseries(title, sql, x, y, w, h, pid, draw="bars", unit="short",
               axis_label="", overrides=None, legend_calcs=None, stacking="none",
               fill=80, line_width=1, palette="palette-classic", description=None):
    p = {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": palette},
                "custom": {
                    "axisBorderShow": False,
                    "axisCenteredZero": False,
                    "axisColorMode": "text",
                    "axisLabel": axis_label,
                    "axisPlacement": "auto",
                    "barAlignment": 0,
                    "barWidthFactor": 0.6,
                    "drawStyle": draw,
                    "fillOpacity": fill,
                    "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "insertNulls": False,
                    "lineInterpolation": "linear",
                    "lineWidth": line_width,
                    "pointSize": 5,
                    "scaleDistribution": {"type": "linear"},
                    "showPoints": "never" if draw == "bars" else "auto",
                    "showValues": False,
                    "spanNulls": False,
                    "stacking": {"group": "A", "mode": stacking},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "min": 0,
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": 0}]},
                "unit": unit,
            },
            "overrides": overrides or [],
        },
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": {
            "legend": {
                "calcs": legend_calcs or [],
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": True,
            },
            "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"},
        },
        "pluginVersion": "12.3.2",
        "targets": [target(sql, fmt="time_series")],
        "title": title,
        "type": "timeseries",
    }
    if description:
        p["description"] = description
    return p


def table(title, sql, x, y, w, h, pid, overrides=None, sort_by=None, description=None):
    p = {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "custom": {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": 0}]},
            },
            "overrides": overrides or [],
        },
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "id": pid,
        "options": {
            "cellHeight": "sm",
            "footer": {"countRows": False, "fields": "", "reducer": ["sum"], "show": False},
            "showHeader": True,
            "sortBy": sort_by or [],
        },
        "pluginVersion": "12.3.2",
        "targets": [target(sql)],
        "title": title,
        "type": "table",
    }
    if description:
        p["description"] = description
    return p


def ov(name, props):
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def status_col(name):
    return ov(name, [
        {"id": "mappings", "value": PASS_FAIL_MAPPINGS},
        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
    ])


def unit_col(name, unit):
    return ov(name, [{"id": "unit", "value": unit}])


def fixed_color(name, color):
    return ov(name, [{"id": "color", "value": {"fixedColor": color, "mode": "fixed"}}])


def report_link(name):
    return ov(name, [{"id": "links", "value": [
        {"targetBlank": True, "title": "show report", "url": "${__value.raw:raw}"}]}])


# --------------------------------------------------------------------------- build

def build(project, surfaces, campaign_prefix=None):
    """surfaces: list of (label, userinterface_name) tuples."""
    title = f"{project.replace('_', ' ').replace('-', ' ').title()} Quality"
    uid = f"{project}-quality"
    ui_list = ", ".join(v for _, v in surfaces)

    panels = []

    # ---- Row: Health at a Glance ------------------------------------------
    panels.append(row("🏥 Health at a Glance", 0, 100))

    def pass_rate(days):
        return (f"SELECT ROUND(SUM(CASE WHEN success THEN 1 ELSE 0 END)::numeric "
                f"/ NULLIF(count(*), 0) * 100, 1) as \"Pass Rate %\"\n"
                f"FROM script_results\nWHERE {SCOPE}\n"
                f"  AND started_at > now() - interval '{days} days'")

    rate_steps = [{"color": "red", "value": 0}, {"color": "yellow", "value": 80},
                  {"color": "green", "value": 95}]
    panels.append(stat("Pass Rate % (7d)", pass_rate(7), 0, 1, 5, 4, 1,
                       unit="percent", steps=rate_steps,
                       description="Share of passing script runs across the selected surfaces, last 7 days (independent of the dashboard time range)."))
    panels.append(stat("Pass Rate % (30d)", pass_rate(30), 5, 1, 5, 4, 2,
                       unit="percent", steps=rate_steps,
                       description="Same, last 30 days."))
    panels.append(stat("Runs (window)",
                       f"SELECT count(*) as \"Runs\"\nFROM script_results\n"
                       f"WHERE {SCOPE}\n  AND {HOST}\n  AND $__timeFilter(started_at)",
                       10, 1, 4, 4, 3,
                       description="Script runs inside the dashboard time range and Host filter."))
    panels.append(stat("Scripts in Scope",
                       f"SELECT count(DISTINCT script_name) as \"Scripts\"\n"
                       f"FROM script_results\nWHERE {SCOPE}",
                       14, 1, 5, 4, 4,
                       description=f"Distinct script names recorded for {ui_list} (all time)."))
    panels.append(stat("Last Execution",
                       f"SELECT to_char(MAX(started_at), 'YYYY-MM-DD HH24:MI') as \"Last Execution\"\n"
                       f"FROM script_results\nWHERE {SURF}",
                       19, 1, 5, 4, 5,
                       color="text", color_mode="none", graph_mode="none",
                       text_mode="value", unit="", fields="Last Execution"))

    # ---- Row: Last run per surface (repeated stat tiles) -------------------
    panels.append(row("🎯 Last Run per Surface", 5, 101))
    # Two gotchas baked into this tile:
    #  * Numeric 1/0 + value mappings — the stat panel reduces numeric fields
    #    reliably, and the mapping colors then drive the green/red background.
    #  * `${surface:sqlstring}` instead of `$surface` — on a REPEATED panel
    #    Grafana passes the per-repeat scoped value straight through and skips
    #    the SQL datasource's multi-value quoting, so plain `IN ($surface)`
    #    emits `IN (sample-app_tv)` (an unquoted identifier) and the panel errors.
    tile = stat(
        "$surface",
        "SELECT CASE WHEN success THEN 1 ELSE 0 END as \"Last Run\"\n"
        f"FROM script_results\nWHERE team_id='{TEAM_ID}'"
        " AND userinterface_name IN (${surface:sqlstring})\n"
        "ORDER BY started_at DESC\nLIMIT 1",
        0, 6, 24 // max(len(surfaces), 1), 4, 6,
        unit="none", color_mode="background", graph_mode="none", text_mode="value",
        mappings=[{"type": "value", "options": {
            "1": {"color": "green", "index": 0, "text": "✅ PASS"},
            "0": {"color": "red", "index": 1, "text": "❌ FAIL"}}}],
        steps=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        description="Result of the most recent script run on this surface (all time).",
    )
    tile["repeat"] = "surface"
    tile["repeatDirection"] = "h"
    tile["maxPerRow"] = max(len(surfaces), 1)
    panels.append(tile)

    # ---- Row: Execution over time -----------------------------------------
    panels.append(row("📈 Test Execution Over Time", 10, 102))
    panels.append(timeseries(
        "Pass / Fail Timeline",
        "SELECT\n  $__timeGroup(started_at, '1h') as time,\n"
        "  SUM(CASE WHEN success THEN 1 ELSE 0 END) as \"Passed\",\n"
        "  SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as \"Failed\"\n"
        f"FROM script_results\nWHERE {SCOPE}\n  AND {HOST}\n"
        "  AND $__timeFilter(started_at)\nGROUP BY 1 ORDER BY 1",
        0, 11, 12, 8, 7, draw="bars", stacking="normal", fill=80,
        overrides=[fixed_color("Passed", "green"), fixed_color("Failed", "red")]))
    panels[-1]["fieldConfig"]["defaults"]["color"] = {"fixedColor": "semi-dark-green", "mode": "fixed"}
    panels.append(timeseries(
        "Avg Execution Duration — per surface",
        "SELECT\n  $__timeGroupAlias(started_at, '1h'),\n"
        "  userinterface_name AS metric,\n"
        "  ROUND(AVG(execution_time_ms)::numeric / 1000, 2) AS value\n"
        f"FROM script_results\nWHERE {SCOPE}\n  AND {HOST}\n"
        "  AND $__timeFilter(started_at)\n"
        "GROUP BY 1, userinterface_name ORDER BY 1",
        12, 11, 12, 8, 8, draw="line", unit="s", axis_label="Duration (s)",
        fill=10, line_width=2, legend_calcs=["mean", "max"]))

    # ---- Row: Run timeline per script --------------------------------------
    panels.append(row("🧭 Run Timeline per Script", 19, 103))
    st = {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "custom": {
                    "fillOpacity": 85,
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "insertNulls": False,
                    "lineWidth": 0,
                    "spanNulls": False,
                },
                "mappings": [
                    {"type": "value", "options": {"1": {"color": "green", "index": 0, "text": "PASS"}}},
                    {"type": "value", "options": {"0": {"color": "red", "index": 1, "text": "FAIL"}}},
                ],
                "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": 0},
                                                             {"color": "green", "value": 1}]},
            },
            "overrides": [],
        },
        "gridPos": {"h": 10, "w": 24, "x": 0, "y": 20},
        "id": 9,
        "options": {
            "alignValue": "center",
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "mergeValues": False,
            "rowHeight": 0.85,
            "showValue": "never",
            "tooltip": {"hideZeros": False, "mode": "single", "sort": "none"},
        },
        "pluginVersion": "12.3.2",
        "targets": [target(
            "SELECT\n  started_at AS time,\n  script_name AS metric,\n"
            "  CASE WHEN success THEN 1 ELSE 0 END AS value\n"
            f"FROM script_results\nWHERE {SCOPE}\n  AND {HOST}\n"
            "  AND $__timeFilter(started_at)\nORDER BY 1",
            fmt="time_series")],
        "title": "Run Timeline per Script (green = pass, red = fail)",
        "type": "state-timeline",
        "description": "One lane per script; each block is a run inside the dashboard time range.",
    }
    panels.append(st)

    # ---- Row: Campaign executions ------------------------------------------
    panels.append(row("🚀 Campaign Executions", 30, 104))
    camp_where = f"{SURF}"
    if campaign_prefix:
        camp_where = f"({SURF} OR campaign_name LIKE '{campaign_prefix}%')"
    panels.append(table(
        "Latest Campaign Executions",
        "SELECT\n  campaign_name AS \"Campaign\",\n"
        "  userinterface_name AS \"Surface\",\n"
        "  host_name AS \"Host\",\n"
        "  started_at AS \"Started\",\n"
        "  CASE WHEN success THEN 'PASS' ELSE 'FAIL' END AS \"Result\",\n"
        "  status AS \"Status\",\n"
        "  execution_time_ms AS \"Duration\",\n"
        "  COALESCE(array_length(script_result_ids, 1), 0) AS \"Scripts\",\n"
        "  html_report_r2_url\n"
        f"FROM campaign_executions\nWHERE team_id='{TEAM_ID}'\n  AND {camp_where}\n"
        "ORDER BY started_at DESC\nLIMIT 30",
        0, 31, 24, 8, 10,
        overrides=[unit_col("Started", "dateTimeAsIso"), status_col("Result"),
                   unit_col("Duration", "ms"), report_link("html_report_r2_url")],
        sort_by=[{"desc": True, "displayName": "Started"}],
        description="Campaign runs for the selected surfaces (and the project campaign prefix, if set). Not limited by the dashboard time range."))

    # ---- Row: Script results ------------------------------------------------
    panels.append(row("📜 Script Results", 39, 105))
    panels.append(table(
        "Scripts — last result, pass % and runs in selected window",
        "WITH scope AS (\n"
        "  SELECT script_name, userinterface_name, success, started_at, execution_time_ms,\n"
        "         host_name, html_report_r2_url\n"
        f"  FROM script_results\n  WHERE {SCOPE}\n    AND {HOST}\n),\n"
        "win AS (\n  SELECT * FROM scope WHERE $__timeFilter(started_at)\n),\n"
        "last AS (\n"
        "  SELECT DISTINCT ON (userinterface_name, script_name)\n"
        "         userinterface_name, script_name, started_at, success, execution_time_ms,\n"
        "         host_name, html_report_r2_url\n"
        "  FROM scope ORDER BY userinterface_name, script_name, started_at DESC\n)\n"
        "SELECT\n  l.userinterface_name AS \"Surface\",\n  l.script_name AS \"Script\",\n"
        "  l.started_at AS \"Last Run\",\n"
        "  CASE WHEN l.success THEN 'PASS' ELSE 'FAIL' END AS \"Last Result\",\n"
        "  l.execution_time_ms AS \"Last Duration\",\n  l.host_name AS \"Host\",\n"
        "  COUNT(w.script_name) AS \"Runs (window)\",\n"
        "  SUM(CASE WHEN w.success THEN 1 ELSE 0 END) AS \"Pass (window)\",\n"
        "  ROUND(SUM(CASE WHEN w.success THEN 1 ELSE 0 END)::numeric"
        " / NULLIF(COUNT(w.script_name), 0) * 100, 1) AS \"Pass % (window)\",\n"
        "  CASE WHEN l.html_report_r2_url IS NOT NULL"
        " THEN '<a href=\"' || l.html_report_r2_url || '\" target=\"_blank\">report</a>' END"
        " AS \"Last Report\"\n"
        "FROM last l\n"
        "LEFT JOIN win w ON w.script_name = l.script_name"
        " AND w.userinterface_name = l.userinterface_name\n"
        "GROUP BY l.userinterface_name, l.script_name, l.started_at, l.success,"
        " l.execution_time_ms, l.host_name, l.html_report_r2_url\n"
        "ORDER BY l.started_at DESC",
        0, 40, 24, 9, 11,
        overrides=[
            unit_col("Last Run", "dateTimeAsIso"),
            status_col("Last Result"),
            unit_col("Last Duration", "ms"),
            ov("Pass % (window)", [
                {"id": "unit", "value": "percent"},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                    {"color": "red", "value": None},
                    {"color": "orange", "value": 50},
                    {"color": "green", "value": 100}]}},
            ]),
            ov("Last Report", [
                {"id": "custom.cellOptions", "value": {"type": "markdown"}},
                {"id": "custom.align", "value": "center"}]),
            ov("Script", [{"id": "custom.width", "value": 280}]),
        ],
        sort_by=[{"desc": True, "displayName": "Last Run"}],
        description="One row per (surface, script). Last Run/Result/Report are all-time; Runs/Pass % follow the dashboard time range and Host filter."))

    barchart = {
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "palette-classic"},
                "custom": {
                    "axisBorderShow": False, "axisCenteredZero": False,
                    "axisColorMode": "text", "axisLabel": "", "axisPlacement": "auto",
                    "fillOpacity": 80, "gradientMode": "none",
                    "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                    "lineWidth": 1, "scaleDistribution": {"type": "linear"},
                    "thresholdsStyle": {"mode": "off"},
                },
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": 0}]},
                "unit": "short",
            },
            "overrides": [fixed_color("Success", "green"), fixed_color("Fail", "red")],
        },
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 49},
        "id": 12,
        "options": {
            "barRadius": 0, "barWidth": 0.7, "fullHighlight": False, "groupWidth": 0.7,
            "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
            "orientation": "vertical", "showValue": "auto", "stacking": "normal",
            "tooltip": {"hideZeros": False, "mode": "multi", "sort": "none"},
            "xField": "Script Name", "xTickLabelRotation": -30, "xTickLabelSpacing": 0,
        },
        "pluginVersion": "12.3.2",
        "targets": [target(
            "SELECT\n  COALESCE(script_name, 'Unknown') as \"Script Name\",\n"
            "  SUM(CASE WHEN success THEN 1 ELSE 0 END) as \"Success\",\n"
            "  SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as \"Fail\"\n"
            f"FROM script_results\nWHERE {SCOPE}\n  AND {HOST}\n"
            "  AND $__timeFilter(started_at)\n"
            "GROUP BY script_name\nORDER BY \"Fail\" DESC, \"Success\" DESC"),
        ],
        "title": "Script Success / Fail",
        "type": "barchart",
    }
    panels.append(barchart)

    panels.append(table(
        "Last 30 Runs",
        "SELECT\n  started_at AS \"Timestamp\",\n  userinterface_name AS \"Surface\",\n"
        "  script_name AS \"Script\",\n  host_name AS \"Host\",\n  device_name AS \"Device\",\n"
        "  CASE WHEN success THEN 'PASS' ELSE 'FAIL' END AS \"Status\",\n"
        "  execution_time_ms AS \"Duration (ms)\",\n  error_msg AS \"Error\",\n"
        "  html_report_r2_url\n"
        f"FROM script_results\nWHERE {SCOPE}\n  AND {HOST}\n"
        "  AND $__timeFilter(started_at)\n"
        "ORDER BY started_at DESC\nLIMIT 30",
        0, 57, 24, 11, 13,
        overrides=[unit_col("Timestamp", "dateTimeAsIso"), status_col("Status"),
                   unit_col("Duration (ms)", "ms"), report_link("html_report_r2_url")],
        sort_by=[{"desc": True, "displayName": "Timestamp"}],
        description="Most recent runs in the dashboard time range. Click html_report_r2_url to open the HTML report."))

    # ---- Templating ---------------------------------------------------------
    surface_query = ", ".join(f"{label} : {ui}" for label, ui in surfaces)
    surface_var = {
        "current": {"text": ["All"], "value": ["$__all"]},
        "includeAll": True,
        "label": "Surface",
        "multi": True,
        "name": "surface",
        "options": [],
        "query": surface_query,
        "type": "custom",
    }
    host_sql = ("SELECT DISTINCT host_name FROM script_results WHERE userinterface_name IN ("
                + ", ".join(f"'{ui}'" for _, ui in surfaces) + ") ORDER BY host_name")
    host_var = {
        "current": {},
        "datasource": DS,
        "definition": host_sql,
        "includeAll": True,
        "label": "Host",
        "multi": True,
        "name": "host",
        "query": host_sql,
        "refresh": 1,
        "regex": "",
        "sort": 1,
        "type": "query",
    }

    return {
        "annotations": {"list": [{
            "builtIn": 1,
            "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard",
        }]},
        "description": f"{title} — black-box test health for the {project} project across its surfaces ({ui_list}). Sibling of the VirtualPyTest Self-Test dashboard.",
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "links": [],
        "panels": panels,
        "preload": False,
        "schemaVersion": 42,
        "tags": [project, "quality", "project"],
        "templating": {"list": [surface_var, host_var]},
        "time": {"from": "now-7d", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "weekStart": "monday",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project slug, e.g. sample-app")
    ap.add_argument("--surface", action="append", required=True, metavar="LABEL=USERINTERFACE",
                    help="surface mapping, repeatable, e.g. --surface tv=sample-app_tv")
    ap.add_argument("--campaign-prefix", default=None,
                    help="also match campaign_executions whose campaign_name starts with this")
    ap.add_argument("--out-dir", default=None,
                    help="output directory (default: ./dashboards next to this script)")
    args = ap.parse_args()

    surfaces = []
    for s in args.surface:
        if "=" not in s:
            ap.error(f"--surface must be LABEL=USERINTERFACE, got {s!r}")
        label, ui = s.split("=", 1)
        surfaces.append((label.strip(), ui.strip()))

    out_dir = args.out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{args.project}-quality.json")

    dash = build(args.project, surfaces, args.campaign_prefix)
    with open(out, "w") as f:
        json.dump(dash, f, indent=2)
        f.write("\n")
    print(f"wrote {out}  uid={dash['uid']}  panels={len(dash['panels'])}  surfaces={len(surfaces)}")


if __name__ == "__main__":
    main()
