"""TASK-43 acceptance prompts, as the MCP calls Atlas makes for them.

Each test drives ``AnalyticsTools`` exactly like ToolBridge does (model arguments plus
private ``_context_*`` keys) and checks the compiled query and the returned artifact.
Rows are faked at the driver boundary, so the SQL that would run is captured, not
executed; the same SQL runs against the database in the parity suite.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.mcp.tools.analytics_tools import AnalyticsTools  # noqa: E402

TEAM = "00000000-0000-0000-0000-000000000123"
CONTEXT = {"_context_team_id": TEAM, "_context_user_id": "user-1", "_context_user_email": "viewer@example.test",
           "_context_user_role": "viewer", "_context_workspace_id": "workspace-1",
           "_context_host_name": "host-a", "_context_device_id": "device1"}


class Registry:
    def get(self, path, params=None):
        return {"hosts": [{"host_name": "host-a", "status": "online", "devices": [
            {"device_id": "device1", "device_name": "living-room-stb", "device_model": "stb", "status": "online"}]}]}


class FakeDriver:
    """Stand-in for psycopg2.connect: records SQL/values and returns canned rows."""

    def __init__(self, rows_for):
        self.rows_for, self.statements = rows_for, []

    def connect(self, dsn, connect_timeout=5):
        driver = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, values=None):
                if values is not None:
                    driver.statements.append((sql, values))
                    self.result = driver.rows_for(sql, values)

            def fetchall(self):
                return self.result

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def set_session(self, **kwargs):
                assert kwargs == {"readonly": True, "autocommit": False}

            def cursor(self, cursor_factory=None):
                return Cursor()
        return Connection()


@pytest.fixture
def tools(monkeypatch):
    def make(rows_for):
        driver = FakeDriver(rows_for)
        monkeypatch.setattr("backend_server.src.lib.analytics.service.psycopg2.connect", driver.connect)
        instance = AnalyticsTools(api_client=Registry())
        instance.service.dsn = "postgresql://readonly@analytics/test"
        return instance, driver
    return make


def _spec(result):
    assert not result["isError"], result["content"][0]["text"]
    return result["artifact"]["content_data"]["artifact_spec"]


def test_failing_testcases_for_this_device(tools):
    """“show failing testcases for this device”"""
    instance, driver = tools(lambda sql, values: [
        {"script_name": "zap_check", "userinterface_name": "stb_tv", "host_name": "host-a",
         "device_name": "living-room-stb", "failure_count": 3, "last_run_at": "2026-10-02T10:00:00+00:00"}])
    spec = _spec(instance.render_analytics_artifact({"preset": "failing_testcases", "scope": "current_device", **CONTEXT}))
    sql, values = driver.statements[0]
    assert "FROM script_results sr" in sql and "(sr.team_id = %s::uuid)" in sql
    assert "sr.success = ANY(%s::boolean[])" in sql and [False] in values
    assert "sr.host_name = %s::text AND sr.device_name = %s::text" in sql
    assert values[values.index("host-a") + 1] == "living-room-stb"
    assert "grafana_device_scope" in sql
    assert spec["mark"] == "table" and spec["data"]["rows"][0]["failure_count"] == 3


def test_compare_pass_rate_by_device(tools):
    """“compare pass rate by device”"""
    instance, driver = tools(lambda sql, values: [
        {"device_name": "living-room-stb", "pass_rate": 92.5, "run_count": 40},
        {"device_name": "bedroom-tv", "pass_rate": 80.0, "run_count": 15}])
    spec = _spec(instance.render_analytics_artifact({"preset": "pass_rate_by_device", **CONTEXT}))
    assert spec["mark"] == "bar" and spec["encoding"]["x"] == "device_name" and spec["encoding"]["y"] == "pass_rate"
    assert "run_count" in spec["encoding"]["tooltip"] and spec["data"]["rows"][0]["run_count"] == 40
    assert "GROUP BY sr.device_name" in driver.statements[0][0]


def test_show_degraded_hosts_uses_fleet_health(tools):
    """“show degraded hosts”"""
    instance, driver = tools(lambda sql, values: [
        {"host_name": "host-a", "device_name": "living-room-stb", "device_model": "stb", "verdict": "DEGRADED",
         "reason": "frozen video", "checked_at": "2026-10-03T09:00:00+00:00"}])
    spec = _spec(instance.render_analytics_artifact({"preset": "degraded_hosts", **CONTEXT}))
    sql, values = driver.statements[0]
    assert "FROM fleet_health f" in sql and "fh.generated_at = fh.latest_generated_at" in sql
    assert ["DEGRADED", "DOWN"] in values and ["live"] in values
    assert spec["provenance"]["source_id"] == "fleet_health_latest"
    assert spec["data"]["rows"][0]["verdict"] == "DEGRADED"


KPI_ROWS = [
    {"action_set_id": f"as_{name}", "variant": variant, "kpi_label": name, "avg_kpi_ms": ms, "sample_count": n}
    for name, variant, ms, n in [
        ("Home", "v1", 1000, 12), ("Home", "v2", 1250, 10), ("Guide", "v1", 900, 8), ("Guide", "v2", 950, 9),
        ("Zap", "v1", 1500, 20), ("Zap", "v2", 1300, 18), ("Replay", "v2", 2000, 3),
    ]]


def test_last_known_kpi_radar_for_stb_tv(tools):
    """“provide the last known KPI radar for userinterface stb_tv”"""
    instance, driver = tools(lambda sql, values: KPI_ROWS)
    result = instance.query_kpi_radar({"userinterface_name": "stb_tv", **CONTEXT})
    spec = _spec(result)
    assert spec["mark"] == "radar" and spec["provenance"]["preset"] == "kpi_radar"
    assert spec["encoding"] == {"x": "kpi_label", "series": "variant", "y": "avg_kpi_ms",
                                "tooltip": ["kpi_label", "avg_kpi_ms", "sample_count", "action_set_id", "variant"],
                                "time_grain": None}
    sql, values = driver.statements[0]
    assert "er.kpi_measurement_ms IS NOT NULL" in sql and ["stb_tv"] in values
    assert spec["options"]["unit"] == "ms"


def test_compare_v1_and_v2_kpi_over_30_days(tools):
    """“compare v1 and v2 KPI for stb_tv over the last 30 days”"""
    instance, driver = tools(lambda sql, values: KPI_ROWS)
    spec = _spec(instance.render_analytics_artifact({
        "preset": "kpi_radar", "filters": {"userinterface_name": "stb_tv", "variant": ["v1", "v2"]},
        "time_range_days": 30,
        "comparison": {"align_by": "kpi_label", "series_field": "variant", "metric": "avg_kpi_ms",
                       "baseline": "v1", "candidate": "v2", "sample_metric": "sample_count"}, **CONTEXT}))
    _, values = driver.statements[0]
    from_time, to_time = values[3], values[4]
    assert (to_time - from_time).days == 30
    assert sorted({row["variant"] for row in spec["data"]["rows"]}) == ["v1", "v2"]
    rows = {row["kpi_label"]: row for row in spec["comparison"]["rows"]}
    assert rows["Home"]["baseline"] == 1000 and rows["Home"]["candidate"] == 1250 and rows["Home"]["percent_delta"] == 25.0
    assert rows["Replay"]["missing"] == "baseline"


def test_only_regressions_over_ten_percent(tools):
    """“show only regressions over 10%”"""
    instance, _ = tools(lambda sql, values: KPI_ROWS)
    result = instance.query_analytics_data({
        "preset": "kpi_radar", "filters": {"userinterface_name": "stb_tv"},
        "comparison": {"baseline": "v1", "candidate": "v2", "regression_over_percent": 10}, **CONTEXT})
    assert not result["isError"]
    rows = result["data"]["comparison"]["rows"]
    assert [row["kpi_label"] for row in rows] == ["Home", "Replay"]
    home = rows[0]
    assert home["regression"] and home["baseline_samples"] == 12 and home["candidate_samples"] == 10
    assert rows[1]["missing"] == "baseline" and rows[1]["candidate_samples"] == 3


def test_canvas_pass_rate_duration_trend_and_failing_cases_for_two_devices(tools):
    """“build a canvas with pass rate, duration trend, and failing cases for these two devices”"""
    def rows_for(sql, values):
        if "date_trunc('day'" in sql:
            return [{"time": "2026-10-01T00:00:00+00:00", "avg_duration_ms": 61000, "run_count": 4}]
        if "FILTER (WHERE NOT sr.success) AS \"failure_count\"" in sql:
            return [{"script_name": "zap_check", "userinterface_name": "stb_tv", "host_name": "host-a",
                     "device_name": "bedroom-tv", "failure_count": 2, "last_run_at": "2026-10-02T10:00:00+00:00"}]
        return [{"device_name": "living-room-stb", "pass_rate": 90.0, "run_count": 10},
                {"device_name": "bedroom-tv", "pass_rate": 70.0, "run_count": 10}]
    instance, driver = tools(rows_for)
    devices = ["living-room-stb", "bedroom-tv"]
    spec = _spec(instance.render_analytics_artifact({
        "title": "Two devices", "filters": {"device_name": devices},
        "panels": [{"preset": "pass_rate_by_device"}, {"preset": "duration_trend"}, {"preset": "failing_testcases"}],
        **CONTEXT}))
    assert spec["kind"] == "canvas" and len(spec["panels"]) == 3
    assert [panel["mark"] for panel in spec["panels"]] == ["bar", "line", "table"]
    assert all(panel["schema"] == "vpt-artifact/v1" for panel in spec["panels"])
    assert len(driver.statements) == 3 and all(devices in values for _, values in driver.statements)


def test_kpi_radar_shortcut_compares_with_only_baseline_and_candidate(tools):
    """The comparison defaults to the chart's category, series, metric and sample count."""
    instance, _ = tools(lambda sql, values: KPI_ROWS)
    spec = _spec(instance.query_kpi_radar({"userinterface_name": "stb_tv", "variants": ["v1", "v2"],
                                           "comparison": {"baseline": "v1", "candidate": "v2"}, **CONTEXT}))
    comparison = spec["comparison"]
    assert (comparison["align_by"], comparison["series_field"], comparison["metric"], comparison["sample_metric"]) == (
        "kpi_label", "variant", "avg_kpi_ms", "sample_count")
    assert {row["kpi_label"] for row in comparison["rows"]} == {"Home", "Guide", "Zap", "Replay"}


def test_export_reply_carries_the_real_content(tools):
    """Live smoke: the reply said only 'Exported 15 rows' and the model invented the CSV."""
    instance, _ = tools(lambda sql, values: [{"device_name": "living-room-stb", "pass_rate": 92.5, "run_count": 40}])
    result = instance.export_analytics_data({"preset": "pass_rate_by_device", "format": "csv", **CONTEXT})
    text = result["content"][0]["text"]
    assert "never invent rows" in text
    assert "device_name,pass_rate,run_count\r\nliving-room-stb,92.5,40" in text


def test_render_reply_lists_every_comparison_row(tools):
    """Live smoke: the reply showed 5 sample data rows, so Atlas reported 1 regression out of 5."""
    instance, _ = tools(lambda sql, values: KPI_ROWS)
    result = instance.render_analytics_artifact({
        "preset": "kpi_radar", "filters": {"userinterface_name": "stb_tv"},
        "comparison": {"baseline": "v1", "candidate": "v2", "regression_over_percent": 10}, **CONTEXT})
    text = result["content"][0]["text"]
    assert "only regressions over 10.0%" in text and "2 rows, all listed" in text
    # Live: 5 regressions + 18 one-sided rows were reported as "23 KPIs affected".
    assert "1 regressions, 1 with one side missing (not regressions" in text
    assert '"kpi_label": "Home"' in text and '"kpi_label": "Replay"' in text


def test_two_variants_are_compared_automatically(tools):
    """Live on the main server: without a comparison Atlas diffed the radar by hand and missed one."""
    instance, _ = tools(lambda sql, values: KPI_ROWS)
    spec = _spec(instance.query_kpi_radar({"userinterface_name": "stb_tv", "variants": ["v1", "v2"], **CONTEXT}))
    assert spec["comparison"]["baseline"] == "v1" and spec["comparison"]["candidate"] == "v2"
    spec = _spec(instance.query_kpi_radar({"userinterface_name": "stb_tv", **CONTEXT}))
    assert "comparison" not in spec


def test_partial_comparison_is_filled_from_the_two_variants(tools):
    """Live: Atlas sent only a threshold and a wrong direction."""
    instance, _ = tools(lambda sql, values: KPI_ROWS)
    spec = _spec(instance.query_kpi_radar({"userinterface_name": "stb_tv", "variants": ["v1", "v2"],
                                           "comparison": {"direction": "higher_is_better", "regression_over_percent": 10},
                                           **CONTEXT}))
    comparison = spec["comparison"]
    assert comparison["direction"] == "lower_is_better"
    assert [row["kpi_label"] for row in comparison["rows"]] == ["Home", "Replay"]
