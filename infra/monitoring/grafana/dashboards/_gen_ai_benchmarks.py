#!/usr/bin/env python3
"""Generate infra/monitoring/grafana/dashboards/ai-benchmarks.json (TASK-143).

The benchmark cases are AI calls: they live in ``public.ai_calls`` with the stats label
``eval:<usage key>`` and ``ref_type = 'benchmark'``. The verdict of a case is ``parse_ok``,
the case id is ``ref_kind``, the latency is ``latency_ms``.
"""
import json
import os

DS = {"type": "grafana-postgresql-datasource", "uid": "supabase-postgres"}

# The rows of one benchmark: the eval calls the runner made.
FROM = ("FROM public.ai_calls "
        "WHERE $__timeFilter(ts) AND ref_type = 'benchmark' AND outcome <> 'skipped' "
        "AND split_part(usage_key, ':', 2) LIKE ANY (ARRAY[$usage_key])")
KEY = "split_part(usage_key, ':', 2)"


def panel(pid, title, x, y, w, h, sql, ptype="timeseries", unit=None, stack=False, desc=""):
    p = {
        "id": pid,
        "type": ptype,
        "title": title,
        "description": desc,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": DS,
        "fieldConfig": {"defaults": {"unit": unit or "short",
                                     "custom": {"drawStyle": "bars" if stack else "line",
                                                "stacking": {"mode": "normal" if stack else "none"}}}},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
        "targets": [{"refId": "A", "format": "time_series", "rawSql": sql}],
    }
    if ptype == "table":
        p["options"] = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    return p


dash = {
    "annotations": {"list": [{
        "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
        "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts", "type": "dashboard"}]},
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 1,
    "links": [],
    "tags": ["ai", "benchmark", "task-143"],
    "templating": {"list": [{
        "current": {"text": "All", "value": "$__all"},
        "datasource": DS,
        "definition": ("SELECT DISTINCT split_part(usage_key, ':', 2) FROM public.ai_calls "
                       "WHERE ref_type = 'benchmark' ORDER BY 1"),
        "includeAll": True,
        "allValue": "%",
        "label": "Usage key",
        "multi": True,
        "name": "usage_key",
        "query": ("SELECT DISTINCT split_part(usage_key, ':', 2) FROM public.ai_calls "
                  "WHERE ref_type = 'benchmark' ORDER BY 1"),
        "refresh": 1,
        "regex": "",
        "sort": 1,
        "type": "query"}]},
    "time": {"from": "now-30d", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "title": "AI benchmarks (TASK-143)",
    "uid": "vpt-ai-benchmarks",
    "version": 1,
    "panels": [
        panel(1, "Pass rate by usage key and model", 0, 0, 12, 9,
              f"SELECT {KEY} AS \"Usage key\", model AS \"Model\", "
              "ROUND(100.0 * COUNT(*) FILTER (WHERE parse_ok) "
              "/ NULLIF(COUNT(*) FILTER (WHERE parse_ok IS NOT NULL), 0), 1) AS \"Pass rate %\", "
              "COUNT(*) FILTER (WHERE parse_ok IS NOT NULL) AS \"Cases\", "
              "COUNT(*) FILTER (WHERE parse_ok IS FALSE) AS \"Failed\" "
              f"{FROM} "
              "GROUP BY 1, 2 ORDER BY 1, 3 DESC",
              ptype="table", unit="percent",
              desc="Which named model answers which usage key best. One row per usage key and model."),
        panel(2, "Cost per model", 12, 0, 12, 9,
              "SELECT model AS \"Model\", ROUND(SUM(cost)::numeric, 6) AS \"Cost USD\", "
              "COUNT(*) AS \"Cases\", ROUND(AVG(latency_ms)) AS \"Avg ms\" "
              f"{FROM} "
              "GROUP BY 1 ORDER BY 2 DESC",
              ptype="table", unit="currencyUSD",
              desc="What the benchmark of each model cost, and how fast it answered."),
        panel(3, "Pass rate over time", 0, 9, 12, 8,
              "SELECT date_trunc('hour', ts) AS time, model AS \"Model\", "
              "ROUND(100.0 * COUNT(*) FILTER (WHERE parse_ok) "
              "/ NULLIF(COUNT(*) FILTER (WHERE parse_ok IS NOT NULL), 0), 1) AS \"Pass rate %\" "
              f"{FROM} "
              "GROUP BY 1, 2 ORDER BY 1",
              unit="percent",
              desc="A model's pass rate over time: a drop after a route change is the signal to read."),
        panel(4, "Cases per day", 12, 9, 12, 8,
              "SELECT date_trunc('day', ts) AS time, COUNT(*) AS \"Cases\", "
              "COUNT(*) FILTER (WHERE parse_ok) AS \"Passed\", "
              "COUNT(*) FILTER (WHERE error_type IS NOT NULL) AS \"Errors\" "
              f"{FROM} "
              "GROUP BY 1 ORDER BY 1",
              desc="How many benchmark cases ran each day, and how many passed or errored."),
        panel(5, "Latency per model", 0, 17, 12, 8,
              "SELECT date_trunc('hour', ts) AS time, model AS \"Model\", "
              "ROUND(AVG(latency_ms)) AS \"Avg ms\", ROUND(MAX(latency_ms)) AS \"Max ms\" "
              f"{FROM} "
              "GROUP BY 1, 2 ORDER BY 1",
              unit="ms",
              desc="How long each model took to answer the frozen cases."),
        panel(6, "Failing cases by usage key", 12, 17, 12, 8,
              f"SELECT {KEY} AS \"Usage key\", model AS \"Model\", ref_kind AS \"Case\", "
              "COALESCE(error_type, 'check failed') AS \"Why\" "
              f"{FROM} AND parse_ok IS FALSE "
              "ORDER BY ts DESC LIMIT 200",
              ptype="table",
              desc="The cases that did not pass, with the reason, newest first."),
    ],
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai-benchmarks.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(dash, f, indent=2)
    f.write('\n')
print('wrote', out)
