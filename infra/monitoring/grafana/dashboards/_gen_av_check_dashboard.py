"""Build the "AV Check Results" Grafana dashboard for test_scripts/av_check.py.

House pattern, same as features/avq/grafana/_gen_avq_dashboard.py: this script
writes the dashboard JSON next to itself and the JSON is what gets pushed to
Grafana. Re-run it after editing a panel and push the new JSON.

What the dashboard shows, all from `script_results` (the table the platform
writes for every script run):

  * the run overview - how many av_check runs, how many passed, the pass rate;
  * the verdict split over time - PASS / VIDEO / AUDIO / NAVIGATION / SCRIPT ERROR,
    read from the run's own error message ("video: ...", "audio: ...");
  * the pass rate per device over time;
  * the per-device table - runs, pass rate, how many video vs audio failures;
  * the failure reasons, with the last time each one was seen;
  * the recent runs, with a link that opens the run's report.

The device scope is the platform's own: `grafana_device_scope()` and
`grafana_user_workspaces()` decide which devices the viewer may see, so a
dashboard on a shared Grafana never shows another team's devices.
"""

import json
import os

DS = {"uid": "supabase-postgres"}
PUBLIC = "https://virtualpytest.angelstreet.io"

# The platform's device scope: the same wrapper the "Script Results" dashboard
# uses, so av_check follows the permissions of the viewer.
SCOPE = (
    "(SELECT * FROM (SELECT * FROM script_results /*device-scope*/ WHERE "
    "('*' = ANY(string_to_array(${allowed_devices:sqlstring}, '|')) OR "
    "host_name || ':' || device_name = ANY(string_to_array(${allowed_devices:sqlstring}, '|')))) "
    "script_results WHERE ('${flag}' = '__ALL__' OR EXISTS (SELECT 1 FROM "
    "(SELECT * FROM device_flags /*device-scope*/ WHERE "
    "('*' = ANY(string_to_array(${allowed_devices:sqlstring}, '|')) OR "
    "host_name || ':' || device_id = ANY(string_to_array(${allowed_devices:sqlstring}, '|')))) df "
    "WHERE df.host_name = script_results.host_name AND df.device_name = script_results.device_name "
    "AND df.flags && string_to_array('${flag:csv}', ',')))) script_results"
)

# What the run's own error message says about the verdict. av_check writes
# "video: ...", "audio: ..." or both; a navigation or a crash is its own thing.
VERDICT = """CASE
  WHEN success THEN 'PASS'
  WHEN error_msg LIKE 'video:%' AND error_msg LIKE '%audio:%' THEN 'VIDEO + AUDIO'
  WHEN error_msg LIKE 'video:%' THEN 'VIDEO'
  WHEN error_msg LIKE 'audio:%' THEN 'AUDIO'
  WHEN error_msg LIKE 'Navigation failed%' THEN 'NAVIGATION'
  WHEN error_msg LIKE 'Script crashed%' THEN 'SCRIPT ERROR'
  ELSE 'OTHER' END"""

# The av_check rows inside the device scope, with the dashboard's own filters.
BASE = f"""FROM {SCOPE}
WHERE $__timeFilter(started_at)
  AND script_name = 'av_check'
  AND (host_name IN ($host) OR host_name IS NULL)
  AND (device_name IN ($device_name) OR device_name IS NULL)
  AND (userinterface_name IN ($user_interface) OR userinterface_name IS NULL)"""


def base_ts(title, x, y, w, h, pid, mn=None, mx=None, stacking=None):
    custom = {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}
    if stacking:
        custom["stacking"] = {"mode": stacking}
        custom["fillOpacity"] = 60
    fc = {"defaults": {"custom": custom}, "overrides": []}
    if mn is not None:
        fc["defaults"]["min"] = mn
    if mx is not None:
        fc["defaults"]["max"] = mx
    return {"datasource": DS, "title": title, "type": "timeseries",
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "id": pid, "fieldConfig": fc,
            "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "multi"}}, "targets": []}


def tgt(sql):
    return {"datasource": DS, "format": "time_series", "rawQuery": True, "rawSql": sql}


def table(title, sql, x, y, w, h, pid, overrides=None):
    return {"datasource": DS, "title": title, "type": "table",
            "gridPos": {"x": x, "y": y, "w": w, "h": h}, "id": pid,
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
                            "overrides": overrides or []},
            "targets": [{"datasource": DS, "format": "table", "rawQuery": True, "rawSql": sql}]}


def row(title, y, pid, collapsed=False, panels=None):
    r = {"type": "row", "title": title, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
         "id": pid, "collapsed": collapsed}
    if panels is not None:
        r["panels"] = panels
    return r


def tvar(name, sql, label=None, all_value=None):
    v = {"current": {"text": "All", "value": "$__all"},
         "datasource": {"type": "grafana-postgresql-datasource", "uid": DS["uid"]},
         "definition": sql, "includeAll": True, "label": label or name.capitalize(),
         "multi": True, "name": name, "query": sql, "refresh": 1, "regex": "",
         "sort": 0, "type": "query"}
    if all_value is not None:
        v["allValue"] = all_value
    return v


def scope_var(name, sql, label):
    """The two scope variables, in the shape _apply_device_scope.py writes."""
    return {"current": {} if name == "allowed_devices" else {"text": "None", "value": "none"},
            "datasource": {"type": "grafana-postgresql-datasource", "uid": DS["uid"]},
            "definition": sql, "includeAll": False, "label": label, "multi": False,
            "name": name, "query": sql, "refresh": 1, "regex": "", "sort": 0, "type": "query",
            **({"hide": 2} if name == "allowed_devices" else {})}


yesno = [{"type": "value", "options": {"Yes": {"color": "green", "index": 0},
                                       "No": {"color": "red", "index": 1}}}]


def cbg(col):
    """Colour a Yes/No cell green / red."""
    return {"matcher": {"id": "byName", "options": col},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
                           {"id": "mappings", "value": yesno}]}


def pbg(col):
    """Colour a pass-rate cell: red below 50 %, green from 100 %."""
    return {"matcher": {"id": "byName", "options": col},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
                           {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                               {"color": "red", "value": None},
                               {"color": "orange", "value": 50},
                               {"color": "green", "value": 100}]}}]}


def vbg(col, colors):
    """Colour a verdict cell from a {value: color} map."""
    mappings = [{"type": "value", "options": {v: {"color": c, "index": i}
                                             for i, (v, c) in enumerate(colors.items())}}]
    return {"matcher": {"id": "byName", "options": col},
            "properties": [{"id": "custom.cellOptions", "value": {"type": "color-background"}},
                           {"id": "mappings", "value": mappings}]}


verdict_colors = {"PASS": "green", "VIDEO": "red", "AUDIO": "orange",
                  "VIDEO + AUDIO": "dark-red", "NAVIGATION": "blue",
                  "SCRIPT ERROR": "dark-orange", "OTHER": "text"}

panels = []

# ---------- Overview ----------------------------------------------------------
panels.append(row("Overview", 0, 100))
ov_sql = f"""SELECT
  COUNT(*) AS "Runs",
  COUNT(*) FILTER (WHERE success) AS "Passed",
  COUNT(*) FILTER (WHERE NOT success) AS "Failed",
  ROUND((COUNT(*) FILTER (WHERE success)::decimal / NULLIF(COUNT(*), 0)) * 100, 1) AS "Pass rate %",
  ROUND(AVG(execution_time_ms)::decimal / 1000, 1) AS "Avg duration (s)",
  COUNT(*) FILTER (WHERE NOT success AND error_msg LIKE 'video:%') AS "Video failures",
  COUNT(*) FILTER (WHERE NOT success AND error_msg LIKE 'audio:%') AS "Audio failures"
{BASE}"""
panels.append({"datasource": DS, "title": "Overview", "type": "stat",
               "gridPos": {"x": 0, "y": 1, "w": 24, "h": 5}, "id": 1,
               "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": "text"}},
                               "overrides": []},
               "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""},
                           "colorMode": "none", "graphMode": "none",
                           "textMode": "value_and_name", "justifyMode": "auto"},
               "targets": [{"datasource": DS, "format": "table", "rawQuery": True, "rawSql": ov_sql}]})

# ---------- Main --------------------------------------------------------------
panels.append(row("Main", 6, 101))
p = base_ts("Verdicts over time", 0, 7, 12, 8, 10, stacking="normal")
p["targets"] = [tgt(f"""SELECT $__timeGroupAlias(started_at, '1d'),
  {VERDICT} AS metric, COUNT(*) AS value
{BASE}
GROUP BY 1, 2 ORDER BY 1""")]
panels.append(p)

p = base_ts("Pass rate per device", 12, 7, 12, 8, 11, mn=0, mx=100)
p["targets"] = [tgt(f"""SELECT $__timeGroupAlias(started_at, '1d'),
  device_name AS metric,
  ROUND((SUM(CASE WHEN success THEN 1 ELSE 0 END)::decimal / COUNT(*)) * 100, 1) AS value
{BASE}
GROUP BY 1, 2 ORDER BY 1""")]
p["fieldConfig"]["defaults"]["unit"] = "percent"
panels.append(p)

# ---------- Details (collapsed, the house shape) -------------------------------
# The detail tables live in one collapsed section at the bottom, like the
# "Script Results" dashboard: the dashboard opens on its overview and the tables
# are one click away.
details_row = row("Details", 15, 102, collapsed=True, panels=[])
panels.append(details_row)
by_dev_sql = f"""SELECT
  host_name AS "Host",
  device_name AS "Device",
  COALESCE(metadata->>'device_model', '') AS "Model",
  COUNT(*) AS "Runs",
  COUNT(*) FILTER (WHERE success) AS "Passed",
  ROUND((COUNT(*) FILTER (WHERE success)::decimal / NULLIF(COUNT(*), 0)) * 100, 1) AS "Pass rate %",
  COUNT(*) FILTER (WHERE NOT success AND error_msg LIKE 'video:%') AS "Video failures",
  COUNT(*) FILTER (WHERE NOT success AND error_msg LIKE 'audio:%') AS "Audio failures",
  ROUND(AVG(execution_time_ms)::decimal / 1000, 1) AS "Avg duration (s)",
  to_char(max(started_at), 'YYYY-MM-DD HH24:MI') AS "Last run"
{BASE}
GROUP BY host_name, device_name, metadata->>'device_model'
ORDER BY host_name, device_name"""
details_row["panels"].append(table("By device", by_dev_sql, 0, 16, 24, 8, 20,
                                   overrides=[pbg("Pass rate %")]))

reasons_sql = f"""SELECT
  COALESCE(error_msg, '(no error message)') AS "Reason",
  COUNT(*) AS "Runs",
  to_char(max(started_at), 'YYYY-MM-DD HH24:MI') AS "Last seen"
{BASE}
GROUP BY error_msg
ORDER BY 2 DESC, 3 DESC"""
details_row["panels"].append(table("Failure reasons", reasons_sql, 0, 24, 12, 8, 30))

# The recent runs, with the run id clickable so it opens that run's report.
#
# The report lives in a private bucket, so the link must be the SIGNED url the
# platform stored with the run (`html_report_r2_url`, the same one the app opens)
# - an unsigned path only reaches the app shell, not the report. That url is
# signed for 7 days from the run, which is why the dashboard opens on the last
# 7 days; for older runs the "Device runs" column leads to the app's report
# list for that device, which never expires.
runs_sql = f"""SELECT
  to_char(started_at, 'MM-DD HH24:MI:SS') AS "Time",
  host_name AS "Host",
  device_name AS "Device",
  COALESCE(userinterface_name, '-') AS "Interface",
  {VERDICT} AS "Verdict",
  ROUND(execution_time_ms::decimal / 1000, 1) AS "Duration (s)",
  left(id::text, 8) AS "Run",
  html_report_r2_url AS "Report",
  '{PUBLIC}/test-results/reports?script=av_check&host=' || host_name ||
    '&device=' || replace(device_name, ' ', '%20') AS "Device runs"
{BASE}
ORDER BY started_at DESC
LIMIT 200"""
run_link = {"matcher": {"id": "byName", "options": "Run"},
            "properties": [{"id": "links", "value": [
                {"title": "Open the av_check report", "targetBlank": True,
                 "url": "${__data.fields.Report}"}]}]}
device_runs_link = {"matcher": {"id": "byName", "options": "Device runs"},
                    "properties": [{"id": "links", "value": [
                        {"title": "Open every av_check run of this device in the app",
                         "targetBlank": True,
                         "url": "${__data.fields[Device runs]"}]}]}
hide_report = {"matcher": {"id": "byName", "options": "Report"},
               "properties": [{"id": "custom.hidden", "value": True}]}
details_row["panels"].append(table("Recent runs", runs_sql, 12, 24, 12, 8, 31,
                                   overrides=[vbg("Verdict", verdict_colors), run_link,
                                              device_runs_link, hide_report]))

# ---------- Dashboard ---------------------------------------------------------
dash = {
    "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                              "enable": True, "hide": True, "name": "Annotations & Alerts",
                              "type": "dashboard"}]},
    "description": "AV Check Results - av_check asks a device whether it is really playing sound and "
                   "video. Per-run verdicts (video / audio) from script_results, with a link to every "
                   "run's report.",
    "editable": True, "graphTooltip": 1, "links": [], "panels": panels, "refresh": "1m",
    "schemaVersion": 39, "tags": ["av_check", "script", "testing"],
    "templating": {"list": [
        scope_var("workspace",
                  "SELECT __text, __value FROM (SELECT 0 AS o, 'None' AS __text, 'none' AS __value "
                  "UNION ALL SELECT 1, name, id FROM grafana_user_workspaces(${__user.email:sqlstring}, "
                  "${__user.login:sqlstring})) w ORDER BY o, __text", "Workspace"),
        scope_var("allowed_devices",
                  "SELECT string_agg(device_key, '|') FROM grafana_device_scope(${__user.email:sqlstring}, "
                  "${__user.login:sqlstring}, ${workspace:sqlstring})", "Allowed devices"),
        tvar("host", f"SELECT DISTINCT host_name FROM {SCOPE} WHERE $__timeFilter(started_at) "
                      f"AND script_name = 'av_check' ORDER BY host_name", label="Host"),
        tvar("device_name", f"SELECT DISTINCT device_name FROM {SCOPE} WHERE $__timeFilter(started_at) "
                            f"AND script_name = 'av_check' ORDER BY device_name", label="Device"),
        tvar("user_interface", f"SELECT DISTINCT userinterface_name FROM {SCOPE} "
                               f"WHERE $__timeFilter(started_at) AND script_name = 'av_check' "
                               f"AND userinterface_name IS NOT NULL ORDER BY userinterface_name",
             label="Userinterface"),
        tvar("flag", f"SELECT DISTINCT f AS flag FROM (SELECT * FROM device_flags /*device-scope*/ WHERE "
                     f"('*' = ANY(string_to_array(${{allowed_devices:sqlstring}}, '|')) OR "
                     f"host_name || ':' || device_id = ANY(string_to_array(${{allowed_devices:sqlstring}}, '|')))) "
                     f"device_flags, unnest(flags) f ORDER BY 1", label="Tag", all_value="__ALL__"),
    ]},
    "time": {"from": "now-7d", "to": "now"}, "timepicker": {}, "timezone": "",
    "title": "AV Check Results", "uid": "av-check-results", "version": 1, "weekStart": "",
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "av-check-results.json")
# ensure_ascii=False + a trailing newline: byte for byte what _apply_details_row.py
# writes, so the two tools can be run in any order without fighting each other.
with open(out, "w", encoding="utf-8") as fh:
    json.dump(dash, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print("wrote", out, "panels:", len(panels))
