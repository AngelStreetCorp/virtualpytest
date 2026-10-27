"""Dashboard parity harness for Atlas analytics.

Parity compares what a maintained Grafana panel shows with what Atlas returns for the
equivalent semantic request, against the same database:

* the panel SQL is the maintained dashboard's own ``rawSql``, interpolated the way
  Grafana does it (``$__timeFilter``, ``${var:sqlstring}``, "All" selections, a
  Grafana admin viewer), never a hand-written copy;
* the Atlas side is ``AnalyticsService.build_query`` for an admin of the owning team.

``capture`` stores pseudonymised results (dimension values become ``k1, k2 …``) so the
committed fixture contains no device, host or customer names.  Run it read-only:

    ATLAS_PARITY_DSN=postgresql://… ATLAS_PARITY_TEAM=<team uuid> \\
        python3 -m tests.backend_server.atlas_parity_support --capture
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
DASHBOARDS = ROOT / "infra" / "monitoring" / "grafana" / "dashboards"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "atlas_parity.json"
# Frozen window: every tenant row in it belongs to one team, so team-less dashboard SQL
# and team-filtered Atlas SQL see the same rows.
FROM = "2026-09-17T00:00:00Z"
TO = "2026-10-03T00:00:00Z"
GRAFANA_ADMIN = {"email": "", "login": "admin"}

# Each case: dashboard + panel, the panel's variable overrides, the Atlas request,
# the aligned key columns and compared value columns (dashboard column, Atlas field,
# absolute tolerance).  Tolerances only absorb display rounding (1 vs 2 decimals).
CASES: List[Dict[str, Any]] = [
    {"id": "script_summary", "family": "script", "dashboard": "script-results.json", "panel": {"id": 2},
     "atlas": {"preset": "script_summary"},
     "key": [], "values": [("Nr. of total test", "run_count", 0), ("Nr. of failed test", "failure_count", 0),
                           ("Success Rate", "pass_rate", 0.06)]},
    {"id": "campaign_by_campaign", "family": "script", "dashboard": "campaign-results.json", "panel": {"title": "By Campaign"},
     "atlas": {"preset": "campaign_pass_rate"},
     "key": [("Campaign", "campaign_name")],
     "values": [("Success", "pass_rate", 0.06), ("Avg Time", "avg_duration_ms", 1), ("Volume", "run_count", 0)],
     "tolerate": ["only in atlas"],
     "known_divergence": "The panel's environment filter goes through the campaign's script results, so a run "
                         "that failed before starting any script is hidden; Atlas counts it as a failed run."},
    {"id": "zapping_total", "family": "script", "dashboard": "all-zapping-events.json", "panel": {"id": 10},
     "atlas": {"source_id": "zapping", "dimensions": [], "metrics": ["zap_count"]},
     "key": [], "values": [("Total Zaps", "zap_count", 0)]},
    {"id": "kpi_radar_stb_tv", "family": "kpi", "dashboard": "kpi-measurement.json", "panel": {"id": 19},
     "atlas": {"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}},
     "key": [("variant", "variant"), ("action_set_id", "kpi_label")],
     "values": [("avg_kpi", "avg_kpi_ms", 1)],
     "known_divergence": "The panel groups by the raw variant and action-set id, so a NULL variant and 'Base' "
                         "(or two action sets sharing a label) appear as separate rows with one label; Atlas "
                         "merges them into one axis value. Those keys are reported as ambiguous, not compared."},
    {"id": "active_alerts_by_device", "family": "alerts", "dashboard": "device-alerts-dashboard.json",
     "panel": {"title": "Active Alerts by Device"},
     "atlas": {"preset": "active_alerts_by_device", "from_time": None, "to_time": None},
     "key": [("metric", "device_name")], "values": [("value", "incident_count", 0)]},
    {"id": "fleet_live_per_device", "family": "alerts", "dashboard": "vpt-fleet-health.json", "panel": {"title": "Live — per device"},
     "atlas": {"source_id": "fleet_health_latest", "dimensions": ["host_name", "device_name", "verdict"], "metrics": [],
               "filters": {"run_kind": ["live"]}},
     "key": [("Host", "host_name"), ("Device", "device_name"), ("Verdict", "verdict")], "values": []},
    {"id": "occupancy_by_device", "family": "occupancy", "dashboard": "device-occupancy.json",
     "panel": {"title": "Occupancy % by device"},
     "atlas": {"preset": "occupancy_by_device"},
     "key": [("device", "device")], "values": [("occupancy", "occupancy_percent", 0.01)]},
    {"id": "ookla_averages", "family": "network", "dashboard": "ookla-speedtest.json", "panel": {"id": 3},
     "atlas": {"source_id": "ookla_speedtest", "dimensions": [],
               "metrics": ["avg_download_mbps", "avg_upload_mbps", "avg_packet_loss_percent", "avg_latency_ms"]},
     "key": [], "values": [("Download", "avg_download_mbps", 0.01), ("Upload", "avg_upload_mbps", 0.01),
                           ("Packet Loss Ø", "avg_packet_loss_percent", 0.01), ("Latency Ø", "avg_latency_ms", 0.01)]},
    {"id": "dns_lookup_times", "family": "network", "dashboard": "dns-lookup.json", "panel": {"id": 11},
     "atlas": {"source_id": "dns_lookup", "dimensions": [], "metrics": ["min_lookup_ms", "avg_lookup_ms", "max_lookup_ms"]},
     "key": [], "values": [("Min", "min_lookup_ms", 0.06), ("Avg", "avg_lookup_ms", 0.06), ("Max", "max_lookup_ms", 0.06)]},
    {"id": "superping_quality", "family": "network", "dashboard": "superping.json", "panel": {"id": 23},
     "atlas": {"source_id": "superping", "dimensions": [], "metrics": ["avg_score", "avg_rtt_ms"]},
     "key": [], "values": [("Superping Score", "avg_score", 0.06), ("Round Trip Delay", "avg_rtt_ms", 0.01)]},
    {"id": "service_availability", "family": "system", "dashboard": "system-service-status.json",
     "panel": {"title": "Availability over the selected range"},
     "atlas": {"source_id": "service_availability", "dimensions": ["server_name", "vm", "component"],
               "metrics": ["availability_percent", "minutes_not_ok", "times_not_ok"]},
     "key": [("VM", "vm_label"), ("Component", "component")],
     "values": [("Availability %", "availability_percent", 0.01), ("Minutes not OK", "minutes_not_ok", 1),
                ("Times not OK", "times_not_ok", 0)]},
    {"id": "match_runs_total", "family": "matcher", "dashboard": "fingerprints.json", "panel": {"id": 1},
     "atlas": {"source_id": "match_runs", "dimensions": [], "metrics": ["run_count"]},
     "key": [], "values": [("Total runs (24h)", "run_count", 0)]},
    {"id": "match_runs_matched", "family": "matcher", "dashboard": "fingerprints.json", "panel": {"id": 2},
     "atlas": {"source_id": "match_runs", "dimensions": [], "metrics": ["matched_count"]},
     "key": [], "values": [("Matched", "matched_count", 0)]},
    {"id": "screen_fingerprints_above", "family": "matcher", "dashboard": "fingerprints.json", "panel": {"id": 5},
     "atlas": {"source_id": "screen_fingerprints_counter", "dimensions": [], "metrics": ["above_threshold"]},
     "key": [], "values": [("Above threshold", "above_threshold", 0)]},
]


# --------------------------------------------------------------------------- Grafana emulation

def find_panel(dashboard: Dict[str, Any], selector: Dict[str, Any]) -> Dict[str, Any]:
    def walk(panels: Sequence[Dict[str, Any]]):
        for panel in panels:
            yield panel
            yield from walk(panel.get("panels") or [])
    for panel in walk(dashboard.get("panels") or []):
        if all(panel.get(key) == value for key, value in selector.items()) and panel.get("targets"):
            return panel
    raise KeyError(f"panel {selector} not found")


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class GrafanaInterpolator:
    """Enough of Grafana's postgres interpolation to run maintained panel SQL as an admin viewer."""

    def __init__(self, cursor, dashboard: Dict[str, Any], from_time: str, to_time: str,
                 overrides: Optional[Dict[str, List[str]]] = None):
        self.cursor = cursor
        self.from_time, self.to_time = from_time, to_time
        self.definitions = {v["name"]: v for v in (dashboard.get("templating") or {}).get("list") or []}
        self.values: Dict[str, Tuple[List[str], Dict[str, Any]]] = {}
        self.overrides = overrides or {}
        self._resolving: set = set()

    def _resolve(self, name: str) -> Tuple[List[str], Dict[str, Any]]:
        """Resolve a variable on first use, like Grafana's dependency-ordered refresh."""
        if name not in self.values:
            if name in self._resolving:
                raise ValueError(f"circular Grafana variable {name}")
            self._resolving.add(name)
            variable = self.definitions[name]
            options = list(self.overrides[name]) if name in self.overrides else self._options(variable)
            self.values[name] = (options, variable)
            self._resolving.discard(name)
        return self.values[name]

    def _options(self, variable: Dict[str, Any]) -> List[str]:
        kind = variable.get("type")
        if kind == "custom":
            options = [part.split(" : ")[-1].strip() for part in str(variable.get("query") or "").split(",") if part.strip()]
        elif kind == "query":
            query = variable.get("query")
            query = query.get("query") if isinstance(query, dict) else query
            self.cursor.execute(self.interpolate(str(query)))
            columns = [c.name for c in self.cursor.description]
            index = columns.index("__value") if "__value" in columns else 0
            options = [str(row[index]) for row in self.cursor.fetchall() if row[index] is not None]
        elif kind in {"constant", "textbox"}:
            options = [str(variable.get("query") or "")]
        else:
            current = (variable.get("current") or {}).get("value")
            options = [str(v) for v in (current if isinstance(current, list) else [current]) if v is not None]
        if variable.get("includeAll") or variable.get("multi"):
            return options
        current = (variable.get("current") or {}).get("value")
        if isinstance(current, str) and current in options:
            return [current]
        return options[:1]

    def _format(self, name: str, fmt: Optional[str]) -> str:
        values, variable = self._resolve(name)
        multi = bool(variable.get("includeAll") or variable.get("multi"))
        all_value = variable.get("allValue")
        if multi and all_value:
            return _quote(all_value) if fmt == "sqlstring" else all_value
        if fmt == "csv":
            return ",".join(values)
        if fmt == "raw":
            return ",".join(values)
        if fmt == "sqlstring" or multi:
            return ",".join(_quote(v) for v in values) if values else "''"
        return values[0] if values else ""

    def interpolate(self, sql: str) -> str:
        epoch = lambda iso: int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)  # noqa: E731
        sql = re.sub(r"\$__timeFilter\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
                     lambda m: f"{m.group(1)} BETWEEN '{self.from_time}' AND '{self.to_time}'", sql)
        sql = sql.replace("$__timeFrom()", f"'{self.from_time}'").replace("$__timeTo()", f"'{self.to_time}'")
        sql = sql.replace("${__from}", str(epoch(self.from_time))).replace("${__to}", str(epoch(self.to_time)))
        sql = re.sub(r"\$\{__user\.(email|login)(?::sqlstring)?\}", lambda m: _quote(GRAFANA_ADMIN[m.group(1)]), sql)

        def var(match: re.Match) -> str:
            name = match.group(1) or match.group(3) or match.group(4)
            fmt = match.group(2)
            if name not in self.definitions:
                return match.group(0)
            return self._format(name, fmt)
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([a-z]+))?\}|\[\[([A-Za-z_][A-Za-z0-9_]*)\]\]|\$([A-Za-z_][A-Za-z0-9_]*)", var, sql)


# --------------------------------------------------------------------------- execution

def _plain(value: Any) -> Any:
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def dashboard_rows(cursor, case: Dict[str, Any]) -> List[Dict[str, Any]]:
    dashboard = json.loads((DASHBOARDS / case["dashboard"]).read_text(encoding="utf-8"))
    panel = find_panel(dashboard, case["panel"])
    sql = GrafanaInterpolator(cursor, dashboard, FROM, TO, case.get("variables")).interpolate(panel["targets"][0]["rawSql"])
    cursor.execute(sql)
    columns = [c.name for c in cursor.description]
    rows = [dict(zip(columns, map(_plain, row))) for row in cursor.fetchall()]
    return [_derive_dashboard(case, row) for row in rows]


def _derive_dashboard(case: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    return row


def atlas_request(case: Dict[str, Any]) -> Dict[str, Any]:
    request = {"from_time": FROM, "to_time": TO, "limit": 500, **case["atlas"]}
    return {key: value for key, value in request.items() if value is not None}


def atlas_rows(service, context, case: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = service.query(atlas_request(case), context)["rows"]
    if case["id"] == "service_availability":
        rows = [{**row, "vm_label": f"server · {row['server_name']}" if row["vm"] == "server" else row["vm"]} for row in rows]
    return rows


def atlas_sql_digest(service, context, case: Dict[str, Any]) -> str:
    sql, _, _ = service.build_query(service.preset_request(atlas_request(case)) if case["atlas"].get("preset")
                                    else atlas_request(case), context)
    return hashlib.sha256(sql.encode()).hexdigest()


def align(case: Dict[str, Any], dashboard: List[Dict[str, Any]], atlas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pair rows by key, compare values within tolerance, and pseudonymise keys."""
    def key_of(row: Dict[str, Any], side: int) -> Tuple[str, ...]:
        return tuple(str(row.get(pair[side])) for pair in case["key"])
    dash_index = {key_of(row, 0): row for row in dashboard}
    atlas_index = {key_of(row, 1): row for row in atlas}
    dash_counts: Dict[Tuple[str, ...], int] = {}
    for row in dashboard:
        dash_counts[key_of(row, 0)] = dash_counts.get(key_of(row, 0), 0) + 1
    # A key the panel shows more than once (e.g. raw NULL and 'Base' variants both
    # labelled "Base") cannot be paired with Atlas's single merged row.
    ambiguous = {key for key, count in dash_counts.items() if count > 1}
    keys = sorted(set(dash_index) | set(atlas_index))
    names = {key: f"k{index + 1}" for index, key in enumerate(keys)}
    pairs, mismatches = [], []
    for key in keys:
        d_row, a_row = dash_index.get(key), atlas_index.get(key)
        entry = {"key": names[key], "dashboard": None, "atlas": None}
        if key in ambiguous:
            entry["ambiguous_dashboard_rows"] = dash_counts[key]
            entry["atlas"] = {a: a_row.get(a) for _, a, _ in case["values"]} if a_row else None
            pairs.append(entry)
            continue
        if d_row is not None:
            entry["dashboard"] = {a: d_row.get(d) for d, a, _ in case["values"]}
        if a_row is not None:
            entry["atlas"] = {a: a_row.get(a) for _, a, _ in case["values"]}
        if d_row is None or a_row is None:
            mismatches.append(f"{names[key]} only in {'atlas' if d_row is None else 'dashboard'}")
        else:
            for d, a, tolerance in case["values"]:
                left, right = d_row.get(d), a_row.get(a)
                if left is None and right is None:
                    continue
                if left is None or right is None or abs(float(left) - float(right)) > tolerance:
                    mismatches.append(f"{names[key]}.{a}: dashboard={left} atlas={right}")
        pairs.append(entry)
    tolerated = [m for m in mismatches if any(t in m for t in case.get("tolerate", []))]
    mismatches = [m for m in mismatches if m not in tolerated]
    return {"rows": pairs, "mismatches": mismatches, "tolerated": tolerated, "row_count": len(keys),
            "ambiguous_keys": len(ambiguous), "known_divergence": case.get("known_divergence")}


def run(dsn: str, team_id: str) -> Dict[str, Any]:
    import psycopg2
    sys.path.insert(0, str(ROOT))
    from backend_server.src.lib.analytics import AnalyticsContext, AnalyticsService
    service = AnalyticsService(dsn=dsn)
    context = AnalyticsContext(team_id=team_id, user_role="admin")
    results = {}
    with psycopg2.connect(dsn, connect_timeout=5) as connection:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            for case in CASES:
                dashboard = dashboard_rows(cursor, case)
                atlas = atlas_rows(service, context, case)
                results[case["id"]] = {"family": case["family"], "dashboard": case["dashboard"],
                                       "panel": case["panel"], "atlas_request": case["atlas"],
                                       "atlas_sql_sha256": atlas_sql_digest(service, context, case),
                                       **align(case, dashboard, atlas)}
    return results


def main(argv: Sequence[str]) -> int:
    dsn, team = os.environ.get("ATLAS_PARITY_DSN"), os.environ.get("ATLAS_PARITY_TEAM")
    if not dsn or not team:
        print("Set ATLAS_PARITY_DSN and ATLAS_PARITY_TEAM", file=sys.stderr)
        return 2
    results = run(dsn, team)
    failing = {cid: r["mismatches"] for cid, r in results.items() if r["mismatches"]}
    for cid, result in results.items():
        print(f"{cid:28} rows={result['row_count']:4} mismatches={len(result['mismatches'])}")
    if "--capture" in argv:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps({"window": {"from": FROM, "to": TO},
                                       "captured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                                       "cases": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {FIXTURE.relative_to(ROOT)}")
    for cid, mismatches in failing.items():
        print(cid, mismatches[:5], file=sys.stderr)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
