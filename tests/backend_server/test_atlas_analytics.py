"""Unit coverage for Atlas's allowlisted semantic analytics layer."""

from __future__ import annotations

import csv
import io
import json
import re

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import ANALYTICS_SOURCES, ARTIFACT_PRESETS, AnalyticsContext, AnalyticsService  # noqa: E402
from backend_server.src.lib.analytics.service import AnalyticsValidationError  # noqa: E402
from backend_server.src.mcp.mcp_server import VirtualPyTestMCPServer  # noqa: E402
from backend_server.src.mcp.tools import analytics_tools  # noqa: E402


TEAM = "00000000-0000-0000-0000-000000000123"
CTX = AnalyticsContext(team_id=TEAM, user_id="user-1", user_email="viewer@example.test",
                       user_role="viewer", workspace_id="workspace-1")
ADMIN = AnalyticsContext(team_id=TEAM, user_id="admin-1", user_email="admin@example.test", user_role="admin")

# Tables that carry a team_id column; a source reading one must filter on it directly.
TENANT_TABLES = {"script_results", "campaign_executions", "deployments", "execution_results", "zap_results",
                 "device_info_latest"}


class FakeRegistry:
    def __init__(self, hosts=None):
        self.calls = []
        self.hosts = hosts if hosts is not None else [
            {"host_name": "host-a", "status": "online", "devices": [
                {"device_id": "device1", "device_name": "living-room-stb", "device_model": "stb", "status": "online"},
                {"device_id": "device2", "device_name": "bedroom-tv", "device_model": "android_tv", "status": "offline"}]},
            {"host_name": "host-b", "status": "online", "devices": [
                {"device_id": "device1", "device_name": "lab-phone", "device_model": "android_mobile", "status": "online"}]},
        ]

    def get(self, path, params=None):
        self.calls.append((path, params))
        return {"hosts": self.hosts}


def _request(**overrides):
    request = {
        "source_id": "kpi_measurements",
        "dimensions": ["kpi_name", "variant"],
        "metrics": ["avg_kpi_ms", "sample_count"],
        "filters": {"userinterface_name": "stb-testop"},
        "from_time": "2026-09-01T00:00:00Z",
        "to_time": "2026-10-01T00:00:00Z",
    }
    request.update(overrides)
    return request


def _fake_query(service, rows, source_id, fields):
    captured = []

    def query(request, context):
        captured.append(dict(request))
        return {"model": "analytics-tabular-v1", "source_id": source_id, "fields": fields, "rows": rows,
                "row_count": len(rows), "truncated": False, "units": {}, "time_grain": request.get("time_grain")}
    service.query = query
    return captured


# --------------------------------------------------------------------------- catalog

def test_catalog_exposes_semantics_not_sql():
    service = AnalyticsService(dsn="unused")
    sources = service.list_sources()
    ids = {source["id"] for source in sources}
    assert {"script_results", "campaign_results", "deployment_results", "kpi_measurements", "execution_metrics",
            "alerts", "fleet_health", "fleet_health_latest", "device_occupancy", "device_information",
            "ookla_speedtest", "dns_lookup", "superping", "historical_system_metrics", "device_system_metrics",
            "service_status", "service_availability", "live_system_status"} <= ids
    text = json.dumps(sources) + json.dumps(service.list_presets())
    assert "relation" not in text and "expression" not in text
    assert "SELECT" not in text and "FROM " not in text and "team_id" not in text


def test_every_tenant_source_has_a_direct_team_predicate():
    for source in ANALYTICS_SOURCES.values():
        if source.live:
            continue
        tables = set(re.findall(r"(?:^|\bFROM\s+|\bJOIN\s+)([a-z_]+)\s+[a-z]+\b", source.relation))
        if tables & TENANT_TABLES:
            assert source.team_expression, f"{source.id} reads a tenant table without a team predicate"


def test_every_source_is_device_scoped_or_admin_only():
    for source in ANALYTICS_SOURCES.values():
        if source.live:
            continue
        if source.required_role == "admin":
            assert source.host_expression is None and source.team_expression is None
        else:
            assert source.host_expression, f"{source.id} has no device/host ceiling"


def test_presets_reference_catalog_fields_only():
    for name, preset in ARTIFACT_PRESETS.items():
        source = ANALYTICS_SOURCES[preset["source"]]
        assert set(preset["dimensions"]) <= set(source.dimensions), name
        assert set(preset["metrics"]) <= set(source.metrics), name
        assert set(preset.get("default_filters") or {}) <= {k for k, f in source.dimensions.items() if f.filterable}, name
        assert set(preset.get("required_filters") or []) <= set(source.dimensions), name
        assert preset["mark"] in {"radar", "line", "area", "bar", "stacked-bar", "pie", "scatter", "heatmap", "stat",
                                  "state-timeline", "table"}, name


def test_phase6_presets_cover_every_priority_family():
    families = {ANALYTICS_SOURCES[p["source"]].family for p in ARTIFACT_PRESETS.values()}
    assert {"kpi", "script", "alerts", "occupancy", "network", "system"} <= families
    for required in ("failing_testcases", "pass_rate_by_device", "campaign_pass_rate", "deployment_timeline",
                     "active_alerts_by_device", "degraded_hosts", "fleet_verdicts", "occupancy_by_device",
                     "device_info_latest", "ookla_speed_trend", "dns_success_trend", "superping_by_target",
                     "host_cpu_trend", "service_status_current", "service_availability"):
        assert required in ARTIFACT_PRESETS


def test_every_preset_compiles_for_an_admin():
    service = AnalyticsService(dsn="unused")
    for name, preset in ARTIFACT_PRESETS.items():
        filters = {field: "stb-testop" for field in preset.get("required_filters", [])}
        request = service.preset_request({"preset": name, "filters": filters})
        sql, values, fields = service.build_query(request, ADMIN)
        assert fields == list(preset["dimensions"]) + list(preset["metrics"]), name
        assert sql.count("%s") == len(values), name


# --------------------------------------------------------------------------- query guardrails

def test_query_is_team_time_and_device_scoped():
    sql, values, fields = AnalyticsService(dsn="unused").build_query(_request(), CTX)
    assert sql.startswith("WITH ads AS MATERIALIZED (SELECT device_key FROM grafana_device_scope(%s::text, %s::text, %s::text))")
    assert "b AS (SELECT %s::timestamptz AS range_from, %s::timestamptz AS range_to)" in sql
    assert "(er.team_id = %s::uuid)" in sql
    assert "er.executed_at >= b.range_from AND er.executed_at <= b.range_to" in sql
    assert "ads.device_key = er.host_name || ':' || er.device_name" in sql
    assert "(er.kpi_measurement_ms IS NOT NULL)" in sql
    assert values[:3] == ["viewer@example.test", "", "workspace-1"]
    assert TEAM in values
    assert fields == ["kpi_name", "variant", "avg_kpi_ms", "sample_count"]
    assert sql.count("%s") == len(values)


def test_elevated_role_uses_grafana_admin_login():
    _, values, _ = AnalyticsService(dsn="unused").build_query(_request(), ADMIN)
    assert values[:3] == ["admin@example.test", "admin", ""]


def test_model_values_are_parameters_not_sql():
    hostile = "stb-testop' OR true --"
    sql, values, _ = AnalyticsService(dsn="unused").build_query(_request(filters={"userinterface_name": hostile}), CTX)
    assert hostile not in sql
    assert [hostile] in values


def test_unknown_fields_and_filters_fail_closed():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match="Unsupported fields"):
        service.build_query(_request(metrics=["arbitrary_sql"]), CTX)
    with pytest.raises(AnalyticsValidationError, match="Unsupported filter"):
        service.build_query(_request(filters={"password": "x"}), CTX)
    with pytest.raises(AnalyticsValidationError, match="Unknown analytics source"):
        service.build_query(_request(source_id="pg_shadow"), CTX)
    with pytest.raises(AnalyticsValidationError, match="Fields must not repeat"):
        service.build_query(_request(dimensions=["kpi_name", "kpi_name"]), CTX)


def test_opaque_json_and_time_fields_are_not_filterable():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match="Unsupported filter: error_message"):
        service.build_query({"source_id": "script_results", "filters": {"error_message": "x"}}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Unsupported filter: info"):
        service.build_query({"source_id": "device_information", "filters": {"info": "x"}}, CTX)
    with pytest.raises(AnalyticsValidationError, match="from_time/to_time"):
        service.build_query({"source_id": "script_results", "filters": {"time": "2026-01-01"}}, CTX)
    with pytest.raises(AnalyticsValidationError, match="scalar"):
        service.build_query({"source_id": "script_results", "filters": {"device_name": [{"a": 1}]}}, CTX)
    with pytest.raises(AnalyticsValidationError, match="1 to 100"):
        service.build_query({"source_id": "script_results", "filters": {"device_name": []}}, CTX)


def test_boolean_filters_are_typed():
    service = AnalyticsService(dsn="unused")
    sql, values, _ = service.build_query({"source_id": "script_results", "filters": {"success": "false"}}, CTX)
    assert "sr.success = ANY(%s::boolean[])" in sql and [False] in values
    with pytest.raises(AnalyticsValidationError, match="true/false"):
        service.build_query({"source_id": "script_results", "filters": {"success": "maybe"}}, CTX)


def test_limits_and_sort_are_bounded_and_allowlisted():
    service = AnalyticsService(dsn="unused")
    sql, values, _ = service.build_query(_request(limit=999999, offset=999999), CTX)
    assert sql.endswith("LIMIT %s::int OFFSET %s::int")
    assert values[-2:] == [501, 10000]
    sql, values, _ = service.build_query(_request(sort=[{"field": "avg_kpi_ms", "direction": "desc"}]), CTX)
    assert 'ORDER BY "avg_kpi_ms" DESC NULLS LAST' in sql
    with pytest.raises(AnalyticsValidationError, match="Invalid sort"):
        service.build_query(_request(sort=[{"field": "not_selected", "direction": "desc"}]), CTX)
    with pytest.raises(AnalyticsValidationError, match="Invalid sort"):
        service.build_query(_request(sort=[{"field": "avg_kpi_ms", "direction": "desc; drop"}]), CTX)
    with pytest.raises(AnalyticsValidationError, match="limit must be an integer"):
        service.build_query(_request(limit="ten"), CTX)


def test_time_bounds_are_validated():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match="before"):
        service.build_query(_request(from_time="2026-10-02T00:00:00Z"), CTX)
    with pytest.raises(AnalyticsValidationError, match="Invalid ISO-8601"):
        service.build_query(_request(from_time="yesterday'--"), CTX)


def test_time_grain_buckets_time_dimensions_from_an_allowlist():
    service = AnalyticsService(dsn="unused")
    sql, _, _ = service.build_query({"source_id": "script_results", "dimensions": ["time"], "metrics": ["pass_rate"],
                                     "time_grain": "day"}, CTX)
    assert "date_trunc('day', sr.started_at) AS \"time\"" in sql
    assert "GROUP BY date_trunc('day', sr.started_at)" in sql
    with pytest.raises(AnalyticsValidationError, match="time_grain"):
        service.build_query({"source_id": "script_results", "dimensions": ["time"], "time_grain": "second'"}, CTX)


def test_flag_filter_is_parameterized_scoped_and_has_no_team_column():
    sql, values, _ = AnalyticsService(dsn="unused").build_query(
        _request(filters={"userinterface_name": "stb-testop", "flags": ["lab", "nightly"]}, flag_match_mode="OR"), CTX
    )
    assert "df.flags && %s::text[]" in sql
    assert "df.team_id" not in sql  # device_flags has no team_id column
    assert "ads.device_key = df.host_name || ':' || df.device_id" in sql
    assert ["lab", "nightly"] in values


def test_selected_server_narrows_hosts():
    ctx = AnalyticsContext(team_id=TEAM, user_email="viewer@example.test", selected_server="srv",
                           selected_server_hosts=("host-a",))
    sql, values, _ = AnalyticsService(dsn="unused").build_query({"source_id": "alerts"}, ctx)
    assert "a.host_name = ANY(%s::text[])" in sql and ["host-a"] in values
    ctx_empty = AnalyticsContext(team_id=TEAM, selected_server="srv")
    _, values, _ = AnalyticsService(dsn="unused").build_query({"source_id": "alerts"}, ctx_empty)
    assert ["__no_hosts__"] in values


def test_current_device_scope_resolves_the_trusted_device():
    registry = FakeRegistry()
    service = AnalyticsService(dsn="unused", api_client=registry)
    ctx = AnalyticsContext(team_id=TEAM, user_email="viewer@example.test", host_name="host-a", device_id="device1")
    sql, values, _ = service.build_query({"source_id": "script_results", "scope": "current_device"}, ctx)
    assert "sr.host_name = %s::text AND sr.device_name = %s::text" in sql
    assert values[values.index("host-a") + 1] == "living-room-stb"
    sql, values, _ = service.build_query({"source_id": "alerts", "scope": "current_device"}, ctx)
    assert "a.host_name = %s::text AND a.device_id = %s::text" in sql
    assert values[values.index("host-a") + 1] == "device1"
    with pytest.raises(AnalyticsValidationError, match="No current device"):
        service.build_query({"source_id": "script_results", "scope": "current_device"}, CTX)
    with pytest.raises(AnalyticsValidationError, match="not registered.*scope='visible'"):
        service.build_query({"source_id": "script_results", "scope": "current_device"},
                            AnalyticsContext(team_id=TEAM, host_name="host-a", device_id="device9"))
    with pytest.raises(AnalyticsValidationError, match="unavailable"):
        AnalyticsService(dsn="unused").build_query({"source_id": "script_results", "scope": "current_device"}, ctx)
    with pytest.raises(AnalyticsValidationError, match="no device dimension"):
        service.build_query({"source_id": "historical_system_metrics", "scope": "current_device"}, ctx)
    with pytest.raises(AnalyticsValidationError, match="scope must be"):
        service.build_query({"source_id": "script_results", "scope": "everything"}, ctx)


def test_admin_only_infrastructure_sources():
    service = AnalyticsService(dsn="unused")
    for source_id in ("service_status", "service_availability"):
        with pytest.raises(AnalyticsValidationError, match="administrators"):
            service.build_query({"source_id": source_id}, CTX)
        sql, _, _ = service.build_query({"source_id": source_id}, ADMIN)
        assert "grafana_device_scope" not in sql
    ctx = AnalyticsContext(team_id=TEAM, user_role="admin", selected_server="s1", selected_server_name="primary")
    sql, values, _ = service.build_query({"source_id": "service_status"}, ctx)
    assert "ssc.server_name = %s::text" in sql and "primary" in values


def test_occupancy_is_clipped_to_the_range_like_the_dashboard():
    sql, _, _ = AnalyticsService(dsn="unused").build_query(
        {"source_id": "device_occupancy", "dimensions": ["device"], "metrics": ["occupancy_percent"]}, CTX)
    assert "dcs.started_at < b.range_to AND COALESCE(dcs.ended_at, NOW()) > b.range_from" in sql
    assert "LEAST(COALESCE(dcs.ended_at, NOW()), b.range_to) - GREATEST(dcs.started_at, b.range_from)" in sql
    assert "CROSS JOIN b" in sql


def test_latest_fleet_uses_newest_scoped_check_not_history():
    sql, _, _ = AnalyticsService(dsn="unused").build_query(
        AnalyticsService(dsn="unused").preset_request({"preset": "degraded_hosts"}), CTX)
    assert "max(f.generated_at) OVER (PARTITION BY f.run_kind)" in sql
    assert "(fh.generated_at = fh.latest_generated_at)" in sql
    assert "b.range_from" not in sql


def test_network_families_read_the_keys_their_scripts_write():
    service = AnalyticsService(dsn="unused")
    expectations = {"ookla_speedtest": ("ookla_speedtest", "ping_latency_ms"),
                    "dns_lookup": ("dns_lookuptime", "lookup_time_ms"),
                    "superping": ("superping", "rtt_avg_ms")}
    for source_id, (script, key) in expectations.items():
        source = ANALYTICS_SOURCES[source_id]
        sql, _, _ = service.build_query({"source_id": source_id, "metrics": list(source.metrics)}, CTX)
        assert f"sr.script_name = '{script}'" in sql
        assert f"'{key}'" in sql
        assert "gw_info_latest g WHERE g.team_id = sr.team_id" in sql


def test_query_requires_team_and_configured_datasource():
    service = AnalyticsService(dsn="")
    service.dsn = ""
    with pytest.raises(AnalyticsValidationError, match="team context"):
        service.query({"source_id": "script_results"}, AnalyticsContext(team_id=""))
    with pytest.raises(AnalyticsValidationError, match="not configured"):
        service.query({"source_id": "script_results"}, CTX)


# --------------------------------------------------------------------------- comparison

COMPARISON_DATA = {
    "fields": ["kpi_name", "variant", "avg_kpi_ms", "sample_count"],
    "rows": [
        {"kpi_name": "Home", "variant": "v1", "avg_kpi_ms": 100, "sample_count": 10},
        {"kpi_name": "Home", "variant": "v2", "avg_kpi_ms": 125, "sample_count": 12},
        {"kpi_name": "Guide", "variant": "v2", "avg_kpi_ms": 90, "sample_count": 4},
        {"kpi_name": "Zap", "variant": "v1", "avg_kpi_ms": 200, "sample_count": 7},
        {"kpi_name": "Zap", "variant": "v2", "avg_kpi_ms": 150, "sample_count": 9},
    ],
}
COMPARISON = {"align_by": "kpi_name", "series_field": "variant", "metric": "avg_kpi_ms",
              "baseline": "v1", "candidate": "v2", "sample_metric": "sample_count"}


def test_comparison_aligns_axes_and_discloses_samples_and_missing():
    comparison = AnalyticsService(dsn="unused").compare(COMPARISON_DATA, COMPARISON)
    rows = {row["kpi_name"]: row for row in comparison["rows"]}
    assert rows["Home"]["delta"] == 25 and rows["Home"]["percent_delta"] == 25.0 and rows["Home"]["regression"]
    assert rows["Home"]["baseline_samples"] == 10 and rows["Home"]["candidate_samples"] == 12
    assert rows["Guide"]["missing"] == "baseline" and rows["Guide"]["baseline"] is None
    assert rows["Zap"]["percent_delta"] == -25.0 and not rows["Zap"]["regression"]
    assert [row["kpi_name"] for row in comparison["rows"]] == ["Home", "Zap", "Guide"]


def test_regression_threshold_keeps_one_sided_rows_visible():
    out = AnalyticsService(dsn="unused").compare(COMPARISON_DATA, {**COMPARISON, "regression_over_percent": 10})
    assert [row["kpi_name"] for row in out["rows"]] == ["Home", "Guide"]
    assert out["regression_over_percent"] == 10.0


def test_higher_is_better_inverts_regressions():
    data = {"fields": ["device_name", "version", "pass_rate", "run_count"], "rows": [
        {"device_name": "a", "version": "old", "pass_rate": 90, "run_count": 5},
        {"device_name": "a", "version": "new", "pass_rate": 80, "run_count": 5},
        {"device_name": "b", "version": "old", "pass_rate": 80, "run_count": 5},
        {"device_name": "b", "version": "new", "pass_rate": 85, "run_count": 5}]}
    out = AnalyticsService(dsn="unused").compare(data, {
        "align_by": "device_name", "series_field": "version", "metric": "pass_rate", "baseline": "old",
        "candidate": "new", "sample_metric": "run_count", "direction": "higher_is_better",
        "regression_over_percent": 5})
    assert [row["device_name"] for row in out["rows"]] == ["a"]


def test_comparison_rejects_positional_or_bad_configuration():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match="requires"):
        service.compare(COMPARISON_DATA, {"metric": "avg_kpi_ms"})
    with pytest.raises(AnalyticsValidationError, match="distinct"):
        service.compare(COMPARISON_DATA, {**COMPARISON, "series_field": "kpi_name"})
    # An unrecognised direction is ignored (the metric decides) and noted, never an error.
    result = service.compare(COMPARISON_DATA, {**COMPARISON, "direction": "sideways"})
    assert "sideways" in result["direction_note"] and result["direction"].endswith("_is_better")
    # Live through the Pi server: Atlas sent metric="variant" and got "no regressions".
    with pytest.raises(AnalyticsValidationError, match="numeric metric"):
        service.compare({**COMPARISON_DATA, "source_id": "kpi_measurements"}, {**COMPARISON, "metric": "variant"})


# --------------------------------------------------------------------------- render

def test_radar_overflow_keeps_best_sampled_kpis_and_discloses_the_rest():
    service = AnalyticsService(dsn="unused")
    rows = [{"action_set_id": f"as_{i}", "variant": "Base", "kpi_label": f"KPI-{i:02d}", "avg_kpi_ms": i, "sample_count": i}
            for i in range(25)]
    captured = _fake_query(service, rows, "kpi_measurements", ["action_set_id", "variant", "kpi_label", "avg_kpi_ms", "sample_count"])
    spec = service.render({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}}, CTX)["content_data"]["artifact_spec"]
    assert captured[0]["filters"] == {"environment": ["dev", "test", "prod"], "userinterface_name": "stb-testop"}
    assert spec["mark"] == "radar"
    assert spec["encoding"]["x"] == "kpi_label" and spec["encoding"]["series"] == "variant" and spec["encoding"]["y"] == "avg_kpi_ms"
    assert spec["options"]["category_overflow"]["kept"] == 20
    assert spec["options"]["category_overflow"]["omitted_categories"] == [f"KPI-{i:02d}" for i in range(5)]
    resolved = spec["provenance"].pop("resolved_request")
    assert resolved["filters"]["userinterface_name"] == "stb-testop" and resolved["preset"] == "kpi_radar"
    assert spec["provenance"] == {"source_id": "kpi_measurements", "preset": "kpi_radar", "dashboard_ref": "kpi-measurement.json"}


def test_radar_readability_falls_back_with_reason():
    service = AnalyticsService(dsn="unused")
    rows = [{"kpi_name": f"KPI-{i}", "variant": "v1", "avg_kpi_ms": i, "sample_count": 1} for i in range(25)]
    _fake_query(service, rows, "kpi_measurements", ["kpi_name", "variant", "avg_kpi_ms", "sample_count"])
    spec = service.render({"source_id": "kpi_measurements", "dimensions": ["kpi_name", "variant"],
                           "metrics": ["avg_kpi_ms", "sample_count"], "mark": "radar"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "bar" and spec["options"]["fallback_applied"] == "bar"
    assert "radar needs 3-20 categories" in spec["options"]["fallback_reason"]
    rows = [{"kpi_name": "A", "variant": "v1", "avg_kpi_ms": 1, "sample_count": 1}]
    _fake_query(service, rows, "kpi_measurements", ["kpi_name", "variant", "avg_kpi_ms", "sample_count"])
    spec = service.render({"source_id": "kpi_measurements", "dimensions": ["kpi_name", "variant"],
                           "metrics": ["avg_kpi_ms", "sample_count"], "mark": "radar"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "bar"


def test_dense_categories_fall_back_to_table_but_time_axes_do_not():
    service = AnalyticsService(dsn="unused")
    rows = [{"device_name": f"d{i}", "pass_rate": 50, "run_count": 2} for i in range(60)]
    _fake_query(service, rows, "script_results", ["device_name", "pass_rate", "run_count"])
    spec = service.render({"preset": "pass_rate_by_device"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "table" and spec["options"]["fallback_applied"] == "table"
    rows = [{"time": f"2026-09-{i % 28 + 1:02d}T{i % 24:02d}:00:00+00:00", "pass_rate": 50, "run_count": 2} for i in range(200)]
    _fake_query(service, rows, "script_results", ["time", "pass_rate", "run_count"])
    spec = service.render({"preset": "pass_rate_trend"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "line" and spec["options"]["fallback_applied"] is None
    assert spec["encoding"]["time_grain"] == "day"


def test_render_rejects_unknown_marks_presets_and_encodings():
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [], "script_results", ["device_name", "pass_rate"])
    with pytest.raises(AnalyticsValidationError, match="Unsupported mark"):
        service.render({"source_id": "script_results", "mark": "<script>"}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Unknown artifact preset"):
        service.render({"preset": "drop_tables"}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Missing preset filters"):
        service.preset_request({"preset": "kpi_radar"})  # no context: nothing to default from
    with pytest.raises(AnalyticsValidationError, match="Encoding field"):
        service.render({"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate"],
                        "mark": "bar", "category": "host_name"}, CTX)


def test_canvas_is_bounded_and_shares_filters():
    service = AnalyticsService(dsn="unused")
    captured = _fake_query(service, [{"device_name": "stb", "pass_rate": 90}], "script_results", ["device_name", "pass_rate"])
    panel = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate"], "mark": "stat"}
    artifact = service.render({"title": "Device comparison", "panels": [panel, panel],
                               "filters": {"device_name": ["a", "b"]}, "time_range_days": 7}, CTX)
    spec = artifact["content_data"]["artifact_spec"]
    assert spec["kind"] == "canvas" and len(spec["panels"]) == 2 and spec["layout"]["columns"] == 2
    assert all(request["filters"] == {"device_name": ["a", "b"]} and request["time_range_days"] == 7 for request in captured)
    with pytest.raises(AnalyticsValidationError, match="between 1 and 6"):
        service.render({"panels": [panel] * 7}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Nested canvases"):
        service.render({"panels": [{"panels": [panel]}]}, CTX)


def test_grammar_never_carries_executable_content():
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [{"device_name": "<img src=x onerror=alert(1)>", "pass_rate": 1, "run_count": 1}],
                "script_results", ["device_name", "pass_rate", "run_count"])
    spec = service.render({"preset": "pass_rate_by_device", "title": "javascript:alert(1)"}, CTX)["content_data"]["artifact_spec"]
    allowed = {"schema", "kind", "title", "mark", "data", "encoding", "options", "provenance", "comparison"}
    assert set(spec) <= allowed
    assert not any(callable(value) for value in spec.values())
    assert spec["schema"] == "vpt-artifact/v1"


# --------------------------------------------------------------------------- export

def test_csv_export_neutralizes_formulas_but_not_numbers():
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [{"device_name": "=HYPERLINK(\"x\")", "pass_rate": -5, "run_count": "-5"},
                          {"device_name": "@SUM(A1)", "pass_rate": None, "run_count": "+cmd"}],
                "script_results", ["device_name", "pass_rate", "run_count"])
    export = service.export({"preset": "pass_rate_by_device", "format": "csv"}, CTX)
    rows = list(csv.reader(io.StringIO(export["content"])))
    assert rows[0] == ["device_name", "pass_rate", "run_count"]
    assert rows[1] == ["'=HYPERLINK(\"x\")", "-5", "-5"]
    assert rows[2] == ["'@SUM(A1)", "", "'+cmd"]
    assert export["filename"] == "pass_rate_by_device.csv" and export["mime_type"] == "text/csv"


def test_json_and_comparison_exports():
    service = AnalyticsService(dsn="unused")
    _fake_query(service, COMPARISON_DATA["rows"], "kpi_measurements", COMPARISON_DATA["fields"])
    export = service.export({"source_id": "kpi_measurements", "format": "json", "comparison": COMPARISON}, CTX)
    payload = json.loads(export["content"])
    assert payload["schema"] == "analytics-export-v1" and payload["comparison"]["baseline"] == "v1"
    export = service.export({"source_id": "kpi_measurements", "format": "csv", "comparison": COMPARISON}, CTX)
    header = export["content"].splitlines()[0].split(",")
    assert header[:3] == ["kpi_name", "baseline", "candidate"] and "candidate_samples" in header
    with pytest.raises(AnalyticsValidationError, match="format"):
        service.export({"source_id": "kpi_measurements", "format": "xlsx"}, CTX)


# --------------------------------------------------------------------------- live status

def test_live_status_uses_registry_with_device_ceiling():
    registry = FakeRegistry()
    service = AnalyticsService(dsn="unused", api_client=registry)
    data = service.query({"source_id": "live_system_status", "filters": {"device_status": "offline"}}, ADMIN)
    assert registry.calls == [("/server/system/getAllHosts", {"include_actions": "false"})]
    assert data["source_id"] == "live_system_status"
    assert [row["device_name"] for row in data["rows"]] == ["bedroom-tv"]
    service._allowed_device_keys = lambda context: {"host-b:device1"}
    data = service.query({"source_id": "live_system_status"}, CTX)
    assert [row["device_name"] for row in data["rows"]] == ["lab-phone"]
    with pytest.raises(AnalyticsValidationError, match="Unsupported live status filter"):
        service.query({"source_id": "live_system_status", "filters": {"sql": "x"}}, ADMIN)
    with pytest.raises(AnalyticsValidationError, match="unavailable"):
        AnalyticsService(dsn="unused").query({"source_id": "live_system_status"}, ADMIN)


# --------------------------------------------------------------------------- MCP surface

def test_mcp_discovers_small_analytics_surface_without_private_context():
    tools = {tool["name"]: tool for tool in VirtualPyTestMCPServer().get_available_tools()}
    assert analytics_tools.ANALYTICS_TOOL_NAMES <= set(tools)
    for name in analytics_tools.ANALYTICS_TOOL_NAMES:
        properties = tools[name]["inputSchema"]["properties"]
        assert not any(key.startswith("_context") or key in {"team_id", "sql", "query", "user_role"} for key in properties), name
    assert tools["query_analytics_data"]["inputSchema"]["required"] == []
    assert {"preset", "scope", "time_grain", "comparison"} <= set(tools["query_analytics_data"]["inputSchema"]["properties"])
    assert {"format"} <= set(tools["export_analytics_data"]["inputSchema"]["properties"])
    assert {"ttl_hours", "prefer_existing", "panels"} <= set(tools["create_grafana_draft"]["inputSchema"]["properties"])


def test_tool_bridge_injects_context_for_every_analytics_tool():
    import inspect
    from backend_server.src.agent.core import tool_bridge
    assert "tool_name in ANALYTICS_TOOL_NAMES" in inspect.getsource(tool_bridge.ToolBridge)
    assert tool_bridge.ANALYTICS_TOOL_NAMES is analytics_tools.ANALYTICS_TOOL_NAMES


def test_mcp_tools_route_context_and_hide_driver_errors(monkeypatch):
    tools = analytics_tools.AnalyticsTools()
    seen = {}

    def render(request, context):
        seen["request"], seen["context"] = request, context
        spec = {"kind": "visualization", "title": "Degraded fleet", "mark": "table", "options": {"fallback_applied": None},
                "data": {"row_count": 1, "rows": [{"host_name": "host-a", "verdict": "DEGRADED"}]}}
        return {"title": "Degraded fleet", "content_type": "data-table", "content_data": {"artifact_spec": spec}}
    monkeypatch.setattr(tools.service, "render", render)
    result = tools.render_analytics_artifact({"preset": "degraded_hosts", "_context_team_id": TEAM,
                                              "_context_user_role": "admin", "_context_device_id": "device1"})
    assert not result["isError"]
    assert result["content"][0]["text"].startswith("Displayed to the user in the chat panel — do not render it again.")
    assert "Degraded fleet: table, 1 rows" in result["content"][0]["text"]
    assert seen["context"].team_id == TEAM and seen["context"].user_role == "admin"
    assert not any(key.startswith("_context") for key in seen["request"])

    def broken(request, context):
        raise RuntimeError("connection to 10.0.0.1 failed: password authentication failed for user postgres")
    monkeypatch.setattr(tools.service, "query", broken)
    result = tools.query_analytics_data({"source_id": "script_results", "_context_team_id": TEAM})
    assert result["isError"] and result["content"][0]["text"] == "Analytics query failed."
    result = tools.query_analytics_data({"source_id": "nope", "_context_team_id": TEAM})
    assert result["isError"]


def test_list_tool_returns_presets_without_sql():
    result = analytics_tools.AnalyticsTools().list_analytics_sources({})
    assert {preset["id"] for preset in result["presets"]} == set(ARTIFACT_PRESETS)
    assert "SELECT" not in json.dumps(result)


def test_tool_schemas_name_every_preset_and_source():
    tools = {tool["name"]: tool for tool in VirtualPyTestMCPServer().get_available_tools()}
    preset_text = tools["render_analytics_artifact"]["inputSchema"]["properties"]["preset"]["description"]
    source_text = tools["query_analytics_data"]["inputSchema"]["properties"]["source_id"]["description"]
    assert all(name in preset_text for name in ARTIFACT_PRESETS)
    assert all(name in source_text for name in ANALYTICS_SOURCES)
    assert "PRESET_IDS" not in json.dumps(tools) and "SOURCE_IDS" not in json.dumps(tools)



def test_comparison_direction_comes_from_the_metric():
    """Live: 'higher_is_better' on KPI ms reported a 41% speed-up as the regression."""
    service = AnalyticsService(dsn="unused")
    data = {**COMPARISON_DATA, "source_id": "kpi_measurements"}
    out = service.compare(data, {**COMPARISON, "direction": "higher_is_better", "regression_over_percent": 10})
    assert out["direction"] == "lower_is_better" and "overridden" in out["direction_note"]
    assert [row["kpi_name"] for row in out["rows"]] == ["Home", "Guide"]
    rates = {"source_id": "script_results", "fields": ["device_name", "version", "pass_rate", "run_count"], "rows": [
        {"device_name": "a", "version": "old", "pass_rate": 90, "run_count": 5},
        {"device_name": "a", "version": "new", "pass_rate": 70, "run_count": 5}]}
    out = service.compare(rates, {"align_by": "device_name", "series_field": "version", "metric": "pass_rate",
                                  "baseline": "old", "candidate": "new", "regression_over_percent": 10})
    assert out["direction"] == "higher_is_better" and out["direction_note"] is None
    assert out["rows"][0]["regression"]



def test_empty_result_is_not_a_readability_fallback():
    """Live: 0 rows showed 'Shown as bar … got 0 categories' and an empty chart."""
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [], "kpi_measurements", ["action_set_id", "variant", "kpi_label", "avg_kpi_ms", "sample_count"])
    spec = service.render({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "radar" and spec["options"]["fallback_applied"] is None and spec["data"]["rows"] == []
    tools = analytics_tools.AnalyticsTools()
    tools.service = service
    text = tools.render_analytics_artifact({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"},
                                            "_context_team_id": TEAM})["content"][0]["text"]
    assert "NO DATA matched" in text



def test_selected_server_scope_is_disclosed():
    """Live in the UI: the KPI comparison came back empty on the main server because the KPI
    data lives on another server's hosts, and nothing said so."""
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [], "kpi_measurements", ["action_set_id", "variant", "kpi_label", "avg_kpi_ms", "sample_count"])
    ctx = AnalyticsContext(team_id=TEAM, selected_server="https://main", selected_server_name="Awesomation",
                           selected_server_hosts=("host-a", "host-b"))
    spec = service.render({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}}, ctx)["content_data"]["artifact_spec"]
    assert spec["options"]["scope_note"] == "Limited to the 2 host(s) of the selected server Awesomation"
    spec = service.render({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}}, CTX)["content_data"]["artifact_spec"]
    assert spec["options"]["scope_note"] is None
    tools = analytics_tools.AnalyticsTools()
    tools.service = service
    text = tools.render_analytics_artifact({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"},
                                            "_context_team_id": TEAM, "_context_selected_server": "https://main",
                                            "_context_selected_server_name": "Awesomation",
                                            "_context_selected_server_hosts": ["host-a"]})["content"][0]["text"]
    assert "other servers' hosts is not included" in text and "do not substitute other devices" in text


def test_unknown_request_keys_are_refused_not_ignored():
    """Live: a panel sent "filter" instead of "filters"; it was ignored and the chart covered
    every device under a two-device title."""
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [{"device_name": "a", "pass_rate": 1, "run_count": 1}], "script_results",
                ["device_name", "pass_rate", "run_count"])
    with pytest.raises(AnalyticsValidationError, match="use 'filters' instead of 'filter'"):
        service.render({"preset": "pass_rate_by_device", "filter": {"device_name": "a"}}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Unknown parameter"):
        service.render({"panels": [{"preset": "pass_rate_by_device", "filter": {"device_name": "a"}}]}, CTX)
    with pytest.raises(AnalyticsValidationError, match="Unknown parameter"):
        AnalyticsService(dsn="unused").query({"source_id": "script_results", "where": "1=1"}, CTX)
    assert service.render({"preset": "pass_rate_by_device", "_context_team_id": TEAM}, CTX)


def test_dead_end_errors_tell_the_model_not_to_ask_the_user():
    """TASK-43 W4: 'Missing preset filters' and 'no current device' used to end in the model
    asking the user (live, Pi server) instead of building the canvas."""
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match=r"Do not ask the user.*kpi_measurements"):
        service.preset_request({"preset": "kpi_radar"})
    with pytest.raises(AnalyticsValidationError, match=r"Do not ask the user which devices.*scope='visible'"):
        service.build_query({"source_id": "script_results", "dimensions": ["device_name"],
                             "metrics": ["pass_rate"], "scope": "current_device"}, CTX)


def test_unsupported_fields_error_lists_valid_fields_and_close_matches():
    source = ANALYTICS_SOURCES["script_results"]
    with pytest.raises(AnalyticsValidationError) as exc:
        AnalyticsService(dsn="unused").build_query(
            {"source_id": "script_results", "dimensions": ["device_id"], "metrics": ["passrate", "runs"]}, CTX)
    message = str(exc.value)
    assert "Unsupported fields: ['device_id', 'passrate', 'runs']" in message
    assert "Valid dimensions for script_results" in message and "Valid metrics" in message
    assert "'passrate' -> 'pass_rate'" in message
    assert list(source.metrics)[0] in message and list(source.dimensions)[0] in message
    close = ANALYTICS_SOURCES["script_results"]
    from backend_server.src.lib.analytics.service import _unsupported_fields_message
    typo = _unsupported_fields_message(close, {list(close.dimensions)[0] + "s"}, set())
    assert f"-> '{list(close.dimensions)[0]}'" in typo
    assert len(message) < 2500


# --------------------------------------------------------------------------- round 3 (BUG-0320..0323)

def _incident_request(**overrides):
    return {"source_id": "alerts", "dimensions": ["time"], "metrics": ["incident_count"], **overrides}


def test_time_dimension_without_grain_defaults_from_the_range():
    service = AnalyticsService(dsn="unused")
    sql, _, _ = service.build_query(_incident_request(time_range_days=1), ADMIN)
    assert "date_trunc('hour'" in sql and "GROUP BY date_trunc('hour'" in sql
    sql, _, _ = service.build_query(_incident_request(time_range_days=30), ADMIN)
    assert "date_trunc('day'" in sql
    # An explicit grain always wins; no metrics means raw rows stay raw.
    sql, _, _ = service.build_query(_incident_request(time_grain="week"), ADMIN)
    assert "date_trunc('week'" in sql
    sql, _, _ = service.build_query({"source_id": "alerts", "dimensions": ["time"], "metrics": []}, ADMIN)
    assert "date_trunc" not in sql


def test_defaulted_grain_is_disclosed_in_result_and_artifact():
    service = AnalyticsService(dsn="unused")
    rows = [{"time": "2026-10-01T00:00:00", "incident_count": 4}]

    def run(request, context, source):
        return {"model": "analytics-tabular-v1", "source_id": "alerts", "fields": ["time", "incident_count"],
                "rows": rows, "row_count": 1, "truncated": False, "units": {}, "time_grain": request.get("time_grain")}
    service._run_query = run
    artifact = service.render({**_incident_request(), "mark": "area"}, ADMIN)
    spec = artifact["content_data"]["artifact_spec"]
    assert spec["encoding"]["time_grain"] == "day"
    assert "defaulted to 'day'" in spec["options"]["time_grain_note"]
    explicit = service.render({**_incident_request(time_grain="hour"), "mark": "area"}, ADMIN)
    assert explicit["content_data"]["artifact_spec"]["options"]["time_grain_note"] is None


def test_unknown_or_empty_source_lists_valid_ids_and_close_matches():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError) as empty:
        service.describe_source("")
    assert "Missing analytics source_id" in str(empty.value) and "script_results" in str(empty.value)
    with pytest.raises(AnalyticsValidationError) as typo:
        service.describe_source("script_result")
    assert "did you mean script_results" in str(typo.value) and "kpi_measurements" in str(typo.value)


def test_canvas_panel_errors_name_the_panel():
    service = AnalyticsService(dsn="unused")
    with pytest.raises(AnalyticsValidationError, match=r"Panel 1 'Duration trend': Missing analytics source_id"):
        service.render({"panels": [{"title": "Duration trend", "metrics": ["avg_duration_ms"]}]}, ADMIN)
    with pytest.raises(AnalyticsValidationError, match=r"Panel 2: Missing analytics source_id"):
        service._run_query = lambda *a, **k: {"fields": [], "rows": [], "row_count": 0, "truncated": False, "units": {}}
        service.render({"panels": [{"source_id": "alerts", "metrics": ["incident_count"], "dimensions": []}, {"mark": "bar"}]}, ADMIN)


def test_unmatched_device_filter_is_reported_to_the_model():
    from backend_server.src.mcp.tools import analytics_tools as tools
    service = AnalyticsService(dsn="unused")
    request = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["run_count"],
               "filters": {"device_name": ["samsung SM-G998B", "stb3"]}}

    def run(req, context, source, rows=[{"device_name": "stb3", "run_count": 3}]):
        return {"model": "analytics-tabular-v1", "source_id": "script_results", "fields": ["device_name", "run_count"],
                "rows": rows, "row_count": len(rows), "truncated": False, "units": {}, "time_grain": None}
    service._run_query = run
    artifact = service.render(request, ADMIN)
    assert artifact["content_data"]["artifact_spec"]["options"]["unmatched_filters"] == {"device_name": ["samsung SM-G998B"]}
    text = tools._shown(artifact)
    assert "device_name 'samsung SM-G998B' matched nothing on this server" in text and "do not substitute" in text
    assert "'stb3' matched nothing" not in text
    # Whole result empty: every value is unmatched, and the artifact keeps the filter it applied.
    service._run_query = lambda req, context, source: run(req, context, source, rows=[])
    empty = service.render(request, ADMIN)
    spec = empty["content_data"]["artifact_spec"]
    assert spec["options"]["filters"] == request["filters"]
    assert spec["options"]["unmatched_filters"]["device_name"] == ["samsung SM-G998B", "stb3"]
    assert "matched nothing on this server" in tools._shown(empty)


def test_truncated_result_does_not_claim_a_filter_matched_nothing():
    from backend_server.src.lib.analytics.catalog import ANALYTICS_SOURCES
    from backend_server.src.lib.analytics.service import unmatched_identity_filters
    source = ANALYTICS_SOURCES["script_results"]
    data = {"fields": ["device_name", "run_count"], "rows": [{"device_name": "stb3", "run_count": 3}], "truncated": True}
    assert unmatched_identity_filters(source, {"device_name": ["stb3", "S21x"]}, data) == {}
    assert unmatched_identity_filters(source, {"device_name": ["S21x"]}, {**data, "rows": []}) == {"device_name": ["S21x"]}


def _kpi_rows_service(pick_rows, calls):
    service = AnalyticsService(dsn="unused")

    def run(req, context, source):
        calls.append(req)
        if req.get("dimensions") == ["userinterface_name"]:
            return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": ["userinterface_name", "sample_count"],
                    "rows": pick_rows, "row_count": len(pick_rows), "truncated": False, "units": {}, "time_grain": None}
        rows = [{"action_set_id": "a", "variant": "Base", "kpi_label": "Zap", "avg_kpi_ms": 10, "sample_count": 4}] \
            if req["filters"]["userinterface_name"] == "stb-testop" else []
        return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": req["dimensions"] + req["metrics"],
                "rows": rows, "row_count": len(rows), "truncated": False, "units": {}, "time_grain": None}
    service._run_query = run
    return service


def test_kpi_preset_without_interface_picks_the_one_with_most_samples():
    from backend_server.src.mcp.tools import analytics_tools as tools
    calls = []
    service = _kpi_rows_service([{"userinterface_name": "stb-testop", "sample_count": 9}], calls)
    artifact = service.render({"preset": "kpi_trend", "time_range_days": 7}, ADMIN)
    options = artifact["content_data"]["artifact_spec"]["options"]
    assert options["defaulted_filters"] == {"userinterface_name": "stb-testop"}
    assert "most KPI samples in scope" in options["defaulted_filters_note"]
    assert options["filters"]["userinterface_name"] == "stb-testop"
    pick = calls[0]
    assert pick["sort"] == [{"field": "sample_count", "direction": "desc"}] and pick["limit"] == 1
    assert pick["time_range_days"] == 7 and "userinterface_name" not in pick["filters"]
    assert "most KPI samples in scope" in tools._shown(artifact)


def test_kpi_preset_prefers_the_conversations_interface_without_a_query():
    from dataclasses import replace
    calls = []
    service = _kpi_rows_service([], calls)
    artifact = service.render({"preset": "kpi_slowest"}, replace(ADMIN, userinterface_name="stb-testop"))
    options = artifact["content_data"]["artifact_spec"]["options"]
    assert options["defaulted_filters"] == {"userinterface_name": "stb-testop"}
    assert "current interface" in options["defaulted_filters_note"]
    assert len(calls) == 1 and calls[0]["dimensions"] != ["userinterface_name"]


def test_explicit_interface_is_not_defaulted_and_no_samples_renders_empty():
    calls = []
    service = _kpi_rows_service([], calls)
    explicit = service.render({"preset": "kpi_radar", "filters": {"userinterface_name": "stb-testop"}}, ADMIN)
    assert explicit["content_data"]["artifact_spec"]["options"]["defaulted_filters"] is None
    empty = service.render({"preset": "kpi_radar"}, ADMIN)
    spec = empty["content_data"]["artifact_spec"]
    assert spec["data"]["rows"] == [] and "No user interface has KPI samples" in spec["options"]["defaulted_filters_note"]


def test_bridge_context_carries_the_current_interface():
    from backend_server.src.mcp.tools.analytics_tools import _context
    assert _context({"_context_team_id": "t", "_context_userinterface_name": "stb-testop"}).userinterface_name == "stb-testop"


def _availability_service(rows_by_probe):
    """Empty main query; the availability probe (dimensions userinterface_name+variant) returns rows_by_probe."""
    service = AnalyticsService(dsn="unused")
    calls = []

    def run(request, context, source):
        calls.append(dict(request))
        if request.get("dimensions") == ["userinterface_name", "variant"]:
            return {"rows": rows_by_probe}
        return {"model": "analytics-tabular-v1", "source_id": source.id, "rows": [], "row_count": 0,
                "fields": ["action_set_id", "variant", "kpi_label", "avg_kpi_ms", "sample_count"],
                "truncated": False, "units": {}, "time_grain": None}
    service._run_query = run
    return service, calls


def _kpi_text(service, **params):
    tools = analytics_tools.AnalyticsTools()
    tools.service = service
    return tools.query_kpi_radar({"userinterface_name": "stb-testop", "variants": ["Base", "variant1"],
                                  "time_range_days": 30, "_context_team_id": TEAM, **params})["content"][0]["text"]


def test_empty_kpi_result_says_nothing_exists_and_to_stop():
    service, calls = _availability_service([])
    text = _kpi_text(service)
    assert "NO DATA matched" in text and "none at all" in text and "Answer now; do not run more queries" in text
    assert "variants Base, variant1" in text
    probes = [c for c in calls if c.get("dimensions") == ["userinterface_name", "variant"]]
    assert len(probes) == 1 and "userinterface_name" not in probes[0]["filters"] and "variant" not in probes[0]["filters"]


def test_empty_kpi_result_lists_other_interfaces_and_missing_variants():
    service, _ = _availability_service([
        {"userinterface_name": "web_tv", "variant": "Base", "sample_count": 100},
        {"userinterface_name": "web_tv", "variant": "v2", "sample_count": 20}])
    text = _kpi_text(service)
    assert "web_tv (120 samples)" in text and "do not retry with guessed fields" in text
    service, _ = _availability_service([{"userinterface_name": "stb-testop", "variant": "Base", "sample_count": 5}])
    assert "only for variants: Base" in _kpi_text(service)


def test_non_empty_kpi_result_runs_no_availability_query():
    service = AnalyticsService(dsn="unused")
    calls = []

    def run(request, context, source):
        calls.append(dict(request))
        return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": ["variant"], "rows": [{"variant": "Base"}],
                "row_count": 1, "truncated": False, "units": {}, "time_grain": None}
    service._run_query = run
    service.query(_request(), CTX)
    assert len(calls) == 1


def test_empty_non_kpi_result_still_says_answer_now():
    service = AnalyticsService(dsn="unused")
    _fake_query(service, [], "script_results", ["device_name", "run_count"])
    tools = analytics_tools.AnalyticsTools()
    tools.service = service
    text = tools.render_analytics_artifact({"source_id": "script_results", "dimensions": ["device_name"],
                                            "metrics": ["run_count"], "_context_team_id": TEAM})["content"][0]["text"]
    assert "NO DATA matched" in text and "Answer now; do not run more queries" in text


# --------------------------------------------------------------------------- named devices (BUG-0355)

NAMED_FLEET = [
    {"host_name": "rpi1-host", "device_id": "d1", "device_name": "S21x"},
    {"host_name": "rpi1-host", "device_id": "host", "device_name": "host"},
    {"host_name": "other-host", "device_id": "d2", "device_name": "Phone slot 1"},
    {"host_name": "other-host", "device_id": "d3", "device_name": "samsung SM-G998B"},
    {"host_name": "other-host", "device_id": "d4", "device_name": "Phone"},
]


def test_named_device_mentions_are_whole_phrase_and_case_insensitive():
    from backend_server.src.lib.analytics.named_devices import detect_named_devices
    found = detect_named_devices("Chart pass rate for devices SAMSUNG sm-g998b, phone SLOT 1 and s21x.",
                                 NAMED_FLEET, ["rpi1-host"])
    assert {d["name"]: d["on_server"] for d in found} == {"samsung SM-G998B": False, "Phone slot 1": False, "S21x": True}
    # 'Phone' inside the longer 'Phone slot 1' is not a second mention
    assert "Phone" not in [d["name"] for d in found]
    # substring of a word is no mention: 'host' in 'hosts', 'Phone' in 'telephone'
    assert detect_named_devices("show all hosts and my telephone usage", NAMED_FLEET, ["rpi1-host"]) == []
    # "host" is also an everyday word: never a device mention (see GENERIC_NAMES).
    assert detect_named_devices("status of the host?", NAMED_FLEET, ["rpi1-host"]) == []
    assert detect_named_devices("nothing to see", NAMED_FLEET, ["rpi1-host"]) == []
    # no known server hosts: nothing can be off-server
    assert all(d["on_server"] for d in detect_named_devices("Phone slot 1", NAMED_FLEET, []))


def _named_tools(rows_by_filters, captured):
    service = AnalyticsService(dsn="unused")

    def query(request, context):
        captured.append(dict(request))
        fields = ["device_name", "run_count"]
        return {"model": "analytics-tabular-v1", "source_id": "script_results", "fields": fields,
                "rows": rows_by_filters, "row_count": len(rows_by_filters), "truncated": False, "units": {},
                "time_grain": None}
    service.query = query
    tools = analytics_tools.AnalyticsTools()
    tools.service = service
    return tools


def _ctx(named, **extra):
    return {"_context_team_id": TEAM, "_context_named_devices": named,
            "_context_known_device_names": [d["device_name"] for d in NAMED_FLEET], **extra}


REQ = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["run_count"], "mark": "bar"}


def test_named_devices_on_server_are_filtered_automatically_and_disclosed():
    captured = []
    tools = _named_tools([{"device_name": "S21x", "run_count": 4}], captured)
    named = [{"name": "S21x", "on_server": True}, {"name": "Phone slot 1", "on_server": False}]
    reply = tools.render_analytics_artifact({**REQ, **_ctx(named)})
    assert captured[0]["filters"] == {"device_name": ["S21x"]}
    text = reply["content"][0]["text"]
    assert "Filtered to the devices you named: S21x" in text and "Phone slot 1" in text and "nothing substituted" in text
    captured.clear()
    tools.query_analytics_data({**REQ, **_ctx(named)})
    assert captured[0]["filters"] == {"device_name": ["S21x"]}


def test_named_devices_off_server_return_no_data_and_a_note():
    captured = []
    tools = _named_tools([{"device_name": "other", "run_count": 9}], captured)
    named = [{"name": "Phone slot 1", "on_server": False}, {"name": "samsung SM-G998B", "on_server": False}]
    for call in (tools.render_analytics_artifact, tools.query_analytics_data, tools.export_analytics_data):
        reply = call({**REQ, **_ctx(named)})
        assert "artifact" not in reply and "data" not in reply and "export" not in reply
        text = reply["content"][0]["text"]
        assert "'Phone slot 1'" in text and "are not on this server; nothing was substituted" in text
    assert captured == []  # the database was never asked


def test_named_devices_do_not_override_explicit_filters_or_unnamed_requests():
    captured = []
    tools = _named_tools([{"device_name": "S21x", "run_count": 4}], captured)
    named = [{"name": "S21x", "on_server": True}]
    tools.query_analytics_data({**REQ, "filters": {"device_name": ["stb3"]}, **_ctx(named)})
    assert captured[-1]["filters"] == {"device_name": ["stb3"]}
    tools.query_analytics_data({**REQ, "scope": "current_device", **_ctx(named)})
    assert "filters" not in captured[-1]
    # no devices named: request untouched, no note
    reply = tools.query_analytics_data({**REQ, **_ctx([])})
    assert "filters" not in captured[-1] and "named" not in reply["content"][0]["text"]
    # source without a device_name dimension is not touched
    tools.query_analytics_data({"source_id": "historical_system_metrics", "metrics": ["cpu_percent"], **_ctx(named)})
    assert "device_name" not in (captured[-1].get("filters") or {})


def test_named_devices_apply_per_canvas_panel():
    captured = []
    tools = _named_tools([{"device_name": "S21x", "run_count": 4}], captured)
    named = [{"name": "S21x", "on_server": True}]
    tools.render_analytics_artifact({"panels": [REQ, {**REQ, "filters": {"host_name": "rpi1-host"}}], **_ctx(named)})
    assert captured[0]["filters"] == {"device_name": ["S21x"]}
    assert captured[1]["filters"] == {"host_name": "rpi1-host"}


def test_titles_never_name_devices_outside_the_filter():
    captured = []
    tools = _named_tools([{"device_name": "S21x", "run_count": 4}], captured)
    named = [{"name": "S21x", "on_server": True}]
    reply = tools.render_analytics_artifact({**REQ, "title": "Runs for Phone slot 1 and Phone", **_ctx(named)})
    assert reply["artifact"]["title"] == "Analytics"
    assert reply["artifact"]["content_data"]["artifact_spec"]["title"] == "Analytics"
    assert "title named devices that are not in the filter (Phone slot 1, Phone)" in reply["content"][0]["text"]
    ok = tools.render_analytics_artifact({**REQ, "title": "Runs for S21x", **_ctx(named)})
    assert ok["artifact"]["title"] == "Runs for S21x"
    canvas = tools.render_analytics_artifact({"panels": [{**REQ, "title": "Phone slot 1 runs"}, REQ],
                                              "title": "Phone slot 1 overview", **_ctx(named)})
    spec = canvas["artifact"]["content_data"]["artifact_spec"]
    assert spec["title"] == "Analytics canvas" and spec["panels"][0]["title"] == "Panel 1"


def test_generic_device_names_are_not_mentions():
    from backend_server.src.lib.analytics.named_devices import detect_named_devices
    devices = [{"device_name": "host", "host_name": "vpt-pi1"}, {"device_name": "S21x", "host_name": "vpt-pi1"}]
    assert detect_named_devices("pass rate per host for the last week", devices, ["vpt-pi1"]) == []
    assert [d["name"] for d in detect_named_devices("pass rate of S21x per host", devices, ["vpt-pi1"])] == ["S21x"]
