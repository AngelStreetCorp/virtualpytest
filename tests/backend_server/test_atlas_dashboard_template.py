"""TASK-43 phase 10: the dashboard template, its exclusion from deploys, variable binding, the skill's tool.

No network: Grafana is never contacted.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import AnalyticsContext, AnalyticsService  # noqa: E402
from backend_server.src.lib.analytics import grafana_drafts  # noqa: E402
from backend_server.src.lib.analytics.grafana_drafts import (  # noqa: E402
    DATASOURCE, FILTER_VARIABLES, GrafanaDraftService, TEMPLATE_MARKER, load_template, _template_problems,
)
from backend_server.src.lib.analytics.service import AnalyticsValidationError  # noqa: E402
from backend_server.src.mcp.tools import analytics_tools  # noqa: E402

ROOT = Path(grafana_drafts.PROJECT_ROOT)
DASHBOARDS = ROOT / "infra" / "monitoring" / "grafana" / "dashboards"
TEMPLATE = DASHBOARDS / "template.json"
TEAM = "00000000-0000-0000-0000-000000000123"
CTX = AnalyticsContext(team_id=TEAM, user_id="user-1", user_email="viewer@example.test", workspace_id="ws-1")
STANDARD = ["workspace", "allowed_devices", "host", "device_name", "user_interface", "environment", "flag"]
PASS_BY_DEVICE = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate"], "mark": "bar"}
PASS_OVER_TIME = {"source_id": "script_results", "dimensions": ["time"], "metrics": ["pass_rate"], "time_grain": "day", "mark": "line"}


def _doc():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _service(tmp_path, template_path=None):
    return GrafanaDraftService(AnalyticsService(dsn="unused"), root=tmp_path / "tmp" / "atlas-grafana",
                               template_path=template_path)


def _sql(dashboard, index=0):
    return dashboard["panels"][index]["targets"][0]["rawSql"]


# ------------------------------------------------------------------ the template file
def test_template_is_valid_and_has_the_standard_variables():
    raw = _doc()
    assert _template_problems(raw) == []
    assert TEMPLATE_MARKER in raw["tags"] and raw["description"].startswith("__template")
    assert [v["name"] for v in raw["templating"]["list"]] == STANDARD
    loaded = load_template(TEMPLATE)
    assert loaded.source == "file" and loaded.variable_names == STANDARD
    assert loaded.filter_variables() == FILTER_VARIABLES
    assert 1 <= len(raw["panels"]) <= 3
    for panel in raw["panels"]:
        assert panel["datasource"] == DATASOURCE and panel["targets"][0]["datasource"] == DATASOURCE
        sql = panel["targets"][0]["rawSql"]
        assert "grafana_device_scope(${__user.email:sqlstring}, ${__user.login:sqlstring}, ${workspace:sqlstring})" in sql
        assert "team_id" in sql and "$__timeFilter(" in sql


def test_template_variables_are_the_maintained_definitions():
    template = {v["name"]: v for v in _doc()["templating"]["list"]}
    results = {v["name"]: v for v in json.loads((DASHBOARDS / "script-results.json").read_text())["templating"]["list"]}
    kpi = {v["name"]: v for v in json.loads((DASHBOARDS / "kpi-measurement.json").read_text())["templating"]["list"]}
    strip = grafana_drafts._variable_identity
    for name in ("workspace", "allowed_devices"):
        assert strip(template[name]) == strip(results[name])
    for name in ("host", "device_name", "user_interface"):
        assert template[name]["query"] == results[name]["query"]
        assert template[name]["includeAll"] and template[name]["multi"] and template[name]["allValue"] == "'__all'"
    assert template["environment"]["query"] == results["environment"]["query"] and template["environment"]["allValue"] == "'__all'"
    assert template["flag"]["query"] == kpi["flag"]["query"] and template["flag"]["allValue"] == "__ALL__"


def test_only_template_json_carries_the_template_marker():
    marked = [p.name for p in DASHBOARDS.glob("*.json") if TEMPLATE_MARKER in (json.loads(p.read_text()).get("tags") or [])]
    assert marked == ["template.json"]


# ------------------------------------------------------------------ never deployed
def test_push_script_skips_the_template(tmp_path):
    env = {**os.environ, "GRAFANA_PASS": "unused", "GRAFANA_URL": "http://127.0.0.1:9/grafana"}
    done = subprocess.run([sys.executable, str(DASHBOARDS / "_push_dashboard.py"), str(TEMPLATE)],
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0 and "SKIP" in done.stdout and "uid=" not in done.stdout


def test_device_scope_tooling_and_notes_skip_the_template():
    sys.path.insert(0, str(DASHBOARDS))
    try:
        import _apply_device_scope
    finally:
        sys.path.remove(str(DASHBOARDS))
    files = [f.name for f in _apply_device_scope.dashboard_files()]
    assert "template.json" not in files and "script-results.json" in files
    assert "/template.json" in (ROOT / "scripts" / "release" / "upgrade_notes.py").read_text()
    assert "template" in (ROOT / "scripts" / "release" / "delivery_note.sh").read_text()


def test_template_is_never_a_maintained_panel(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setitem(grafana_drafts.ARTIFACT_PRESETS, "pass_rate_trend", {
        **grafana_drafts.ARTIFACT_PRESETS["pass_rate_trend"], "dashboard_ref": "template.json",
        "dashboard_panel": "Example: pass rate per day by device"})
    assert service.find_maintained({"preset": "pass_rate_trend"}) is None


# ------------------------------------------------------------------ loader: overlay and fallback
def test_an_overlay_template_at_the_same_path_replaces_the_platform_one(tmp_path):
    overlay = _doc()
    overlay["time"] = {"from": "now-3d", "to": "now"}
    overlay["refresh"] = "5m"
    overlay["panels"][1]["gridPos"]["h"] = 11
    extra = copy.deepcopy(next(v for v in overlay["templating"]["list"] if v["name"] == "environment"))
    extra.update(name="site", label="Site", query="HQ : hq,Lab : lab")
    overlay["templating"]["list"].append(extra)
    path = tmp_path / "overlay" / "template.json"
    path.parent.mkdir()
    path.write_text(json.dumps(overlay))
    built = _service(tmp_path, path).build({"title": "T", "panels": [PASS_BY_DEVICE, PASS_OVER_TIME]}, CTX)
    dashboard = built["dashboard"]
    assert dashboard["time"] == {"from": "now-3d", "to": "now"} and dashboard["refresh"] == "5m"
    assert [v["name"] for v in dashboard["templating"]["list"]] == STANDARD + ["site"]
    assert dashboard["panels"][0]["gridPos"]["h"] == 11
    assert built["metadata"]["template"]["variables"] == STANDARD + ["site"]
    # ...and the platform template does not know "site": the same draft is rejected against it.
    assert any("template's variables" in e for e in _service(tmp_path).validate(dashboard, built["metadata"], CTX)["errors"])


def test_drafts_use_the_template_time_settings_styling_and_grid(tmp_path):
    raw = _doc()
    built = _service(tmp_path).build({"title": "T", "panels": [PASS_BY_DEVICE, PASS_OVER_TIME]}, CTX)
    dashboard = built["dashboard"]
    for key in ("time", "refresh", "timezone", "graphTooltip", "schemaVersion", "editable"):
        assert dashboard[key] == raw[key], key
    height = next(p["gridPos"]["h"] for p in raw["panels"] if p["type"] == "timeseries")
    assert [p["gridPos"] for p in dashboard["panels"]] == [{"x": 0, "y": 0, "w": 12, "h": height}, {"x": 12, "y": 0, "w": 12, "h": height}]
    series = next(p for p in dashboard["panels"] if p["type"] == "timeseries")
    example = next(p for p in raw["panels"] if p["type"] == "timeseries")
    assert series["fieldConfig"]["defaults"]["custom"] == example["fieldConfig"]["defaults"]["custom"]
    assert series["options"]["tooltip"] == example["options"]["tooltip"]
    # a request that asks for a range keeps asking for it
    ranged = _service(tmp_path).build({"title": "T", "time_range_days": 14, "panels": [PASS_BY_DEVICE]}, CTX)
    assert ranged["dashboard"]["time"]["from"] == "now-14d"
    assert built["validation"]["errors"] == []


@pytest.mark.parametrize("breakage", ["missing", "not json", "no marker", "foreign datasource", "no workspace"])
def test_unusable_template_falls_back_to_the_builtin_skeleton_with_a_warning(tmp_path, caplog, breakage):
    path = tmp_path / "template.json"
    raw = _doc()
    if breakage == "no marker":
        raw["tags"] = []
    elif breakage == "foreign datasource":
        raw["templating"]["list"][2]["datasource"] = {"type": "prometheus", "uid": "other"}
    elif breakage == "no workspace":
        raw["templating"]["list"] = raw["templating"]["list"][1:]
    if breakage == "not json":
        path.write_text("{oops")
    elif breakage != "missing":
        path.write_text(json.dumps(raw))
    with caplog.at_level(logging.WARNING, logger=grafana_drafts.logger.name):
        template = load_template(path)
    assert template.source == "builtin" and template.variable_names == ["workspace"]
    assert "built-in skeleton" in caplog.text
    built = _service(tmp_path, path).build({"title": "T", "filters": {"device_name": ["a"]}, "panels": [PASS_BY_DEVICE]}, CTX)
    assert built["validation"]["errors"] == []
    assert "'a'" in _sql(built["dashboard"]) and "$device_name" not in _sql(built["dashboard"])  # no variable: literal


# ------------------------------------------------------------------ variable binding
def test_filters_bind_to_template_variables_and_preselect_the_value(tmp_path):
    service = _service(tmp_path)
    request = {"title": "T", "filters": {"device_name": ["Pixel 7", "S21"], "environment": ["prod"], "host_name": ["host-1"]},
               "panels": [PASS_BY_DEVICE, PASS_OVER_TIME]}
    built = service.build(request, CTX)
    dashboard, metadata = built["dashboard"], built["metadata"]
    for index in (0, 1):
        sql = _sql(dashboard, index)
        assert "'__all' IN ($device_name) OR (sr.device_name)::text IN ($device_name) OR (sr.device_name) IS NULL" in sql
        assert "'__all' IN ($environment) OR (sr.environment)::text IN ($environment) OR (sr.environment) IS NULL" in sql
        assert "'__all' IN ($host) OR (sr.host_name)::text IN ($host) OR (sr.host_name) IS NULL" in sql
        assert "Pixel 7" not in sql and "ARRAY[" not in sql
    current = {v["name"]: v["current"] for v in dashboard["templating"]["list"]}
    assert current["device_name"] == {"text": ["Pixel 7", "S21"], "value": ["Pixel 7", "S21"]}
    assert current["environment"]["value"] == ["prod"] and current["host"]["value"] == ["host-1"]
    assert current["user_interface"] == {"text": "All", "value": ["$__all"]}  # untouched
    binding = metadata["panels"][0]["binding"]
    assert binding["mode"] == "variables"
    assert binding["variables"] == {"device_name": "device_name", "environment": "environment", "host_name": "host",
                                    "userinterface_name": "user_interface"}
    assert binding["fixed"]["device_name"] == ["Pixel 7", "S21"]
    assert built["validation"]["errors"] == []  # sha256 recompile matches with the recorded binding
    # the recorded mode is part of what the recompile trusts: forging it breaks the digest
    forged = copy.deepcopy(metadata)
    forged["panels"][0]["binding"] = {"mode": "literal", "variables": {}, "fixed": {}}
    assert any("catalog template" in e for e in service.validate(dashboard, forged, CTX)["errors"])
    unknown = copy.deepcopy(metadata)
    unknown["panels"][0]["binding"]["variables"]["device_name"] = "nope"
    assert any("template does not declare" in e for e in service.validate(dashboard, unknown, CTX)["errors"])


def test_every_panel_with_the_column_is_bound_even_without_a_filter(tmp_path):
    built = _service(tmp_path).build({"title": "T", "panels": [PASS_BY_DEVICE]}, CTX)
    sql = _sql(built["dashboard"])
    for var, col in (("host", "host_name"), ("device_name", "device_name"), ("user_interface", "userinterface_name"),
                     ("environment", "environment")):
        assert f"'__all' IN (${var}) OR (sr.{col})::text IN (${var}) OR (sr.{col}) IS NULL" in sql
    binding = built["metadata"]["panels"][0]["binding"]
    assert binding["mode"] == "variables" and binding["fixed"] == {} and set(binding["variables"].values()) == {
        "host", "device_name", "user_interface", "environment"}
    template = {v["name"]: v for v in _doc()["templating"]["list"]}  # nothing preselected: All
    assert {v["name"]: v for v in built["dashboard"]["templating"]["list"]} == template
    assert built["validation"]["errors"] == []


def test_a_panel_whose_source_lacks_the_column_stays_unbound(tmp_path):
    alerts = grafana_drafts.ANALYTICS_SOURCES["alerts"]
    assert "environment" not in alerts.dimensions
    panel = {"source_id": "alerts", "dimensions": ["device_name"], "metrics": [next(iter(alerts.metrics))], "mark": "bar"}
    built = _service(tmp_path).build({"title": "T", "panels": [PASS_BY_DEVICE, panel]}, CTX)
    assert "environment" not in built["metadata"]["panels"][1]["binding"]["variables"]
    assert "$environment" not in _sql(built["dashboard"], 1) and "$device_name" in _sql(built["dashboard"], 1)
    assert built["validation"]["errors"] == []
    text = analytics_tools._dashboard_summary({"dashboard": built["dashboard"], "metadata": built["metadata"]})
    assert "Variables that do not affect a panel" in text and "Environment: panel 2" in text


def test_a_variable_has_one_value_so_a_disagreeing_panel_stays_literal(tmp_path):
    built = _service(tmp_path).build({"title": "T", "panels": [
        {**PASS_BY_DEVICE, "filters": {"device_name": ["a"]}}, {**PASS_OVER_TIME, "filters": {"device_name": ["b"]}}]}, CTX)
    assert "$device_name" in _sql(built["dashboard"], 0)
    assert "$device_name" not in _sql(built["dashboard"], 1) and "ARRAY['b']" in _sql(built["dashboard"], 1)
    assert "device_name" in built["metadata"]["panels"][0]["binding"]["variables"]
    assert "device_name" not in built["metadata"]["panels"][1]["binding"]["variables"]
    assert "$host" in _sql(built["dashboard"], 1)  # other variables still bind
    current = {v["name"]: v["current"] for v in built["dashboard"]["templating"]["list"]}
    assert current["device_name"]["value"] == ["a"]
    assert built["validation"]["errors"] == []


def test_flag_filter_binds_to_the_flag_variable(tmp_path):
    panel = {"source_id": "kpi_measurements", "dimensions": ["userinterface_name"], "metrics": ["avg_kpi_ms"], "mark": "bar"}
    source = grafana_drafts.ANALYTICS_SOURCES["kpi_measurements"]
    if "avg_kpi_ms" not in source.metrics:
        panel["metrics"] = [next(iter(source.metrics))]
    built = _service(tmp_path).build({"title": "T", "panels": [{**panel, "filters": {"flags": ["lab"]}}]}, CTX)
    sql = _sql(built["dashboard"])
    assert "'${flag}' = '__ALL__' OR EXISTS" in sql and "string_to_array('${flag:csv}', ',')" in sql and "'lab'" not in sql
    assert {v["name"]: v["current"] for v in built["dashboard"]["templating"]["list"]}["flag"]["value"] == ["lab"]
    # "all of" several flags cannot be a variable (the variable means any-of): stays literal
    both = _service(tmp_path).build({"title": "T", "panels": [{**panel, "filters": {"flags": ["a", "b"]}}]}, CTX)
    assert "ARRAY['a', 'b']" in _sql(both["dashboard"]) and "flags" not in both["metadata"]["panels"][0]["binding"]["variables"]


def test_variable_values_follow_the_literal_character_rules(tmp_path):
    for hostile in ("${__user.email}", "a\nb", "$x"):
        with pytest.raises(AnalyticsValidationError, match="Draft filter values"):
            _service(tmp_path).build({"title": "T", "filters": {"device_name": [hostile]}, "panels": [PASS_BY_DEVICE]}, CTX)


def test_validate_accepts_exactly_the_templates_variables(tmp_path):
    service = _service(tmp_path)
    built = service.build({"title": "T", "panels": [PASS_BY_DEVICE]}, CTX)

    def errors(mutate):
        dashboard = copy.deepcopy(built["dashboard"])
        mutate(dashboard)
        return service.validate(dashboard, built["metadata"], CTX)["errors"]

    assert errors(lambda d: None) == []
    variables = lambda d: d["templating"]["list"]  # noqa: E731
    assert errors(lambda d: variables(d).append({"name": "x", "query": "SELECT 1"}))
    assert errors(lambda d: variables(d).pop())
    assert errors(lambda d: variables(d).reverse())
    assert errors(lambda d: variables(d)[2].__setitem__("query", "SELECT secret FROM auth.users"))
    assert errors(lambda d: variables(d)[2].__setitem__("datasource", {"uid": "other"}))
    assert errors(lambda d: variables(d)[3].__setitem__("current", {"text": ["x"], "value": ["x"]}))  # selection nobody fixed


# ------------------------------------------------------------------ the skill's tool pushes once
class RecordingPublisher:
    def __init__(self, exc=None):
        self.calls, self.contexts, self.exc = [], [], exc

    def publish(self, request, context):
        self.calls.append(request)
        self.contexts.append(context)
        if self.exc:
            raise self.exc
        return {"path": "/grafana/d/atlas-draft-1", "uid": "atlas-draft-1",
                "expires_at": "2026-10-06T12:00:00+00:00", "reused": False}


def test_create_grafana_draft_with_panels_pushes_once_and_names_the_variables(tmp_path):
    tools = analytics_tools.AnalyticsTools()
    tools.drafts = _service(tmp_path)
    tools.publisher = RecordingPublisher()
    result = tools.create_grafana_draft({
        "title": "Fleet", "filters": {"device_name": ["Pixel 7"]}, "panels": [PASS_BY_DEVICE, PASS_OVER_TIME],
        "_context_team_id": TEAM})
    assert result["isError"] is False and len(tools.publisher.calls) == 1
    pushed = tools.publisher.calls[0]
    assert len(pushed["panels"]) == 2 and pushed["title"] == "Fleet" and pushed["prefer_existing"] is False
    text = result["content"][0]["text"]
    assert "/grafana/d/atlas-draft-1 (a path on the VirtualPyTest web app" in text and "never add or guess a host) (expires 2026-10-06T12:00:00+00:00)" in text
    assert "Dashboard variables: Workspace, Host, Device, User Interface, Environment, Tag." in text
    assert "Preselected filters (only values the user asked for): Device=Pixel 7." in text


def _draft_text_and_dashboard(tmp_path, params):
    tools = analytics_tools.AnalyticsTools()
    tools.drafts = _service(tmp_path)
    tools.publisher = RecordingPublisher()
    result = tools.create_grafana_draft({"title": "Fleet", "panels": [PASS_BY_DEVICE, PASS_OVER_TIME],
                                         "_context_team_id": TEAM, **params})
    assert result["isError"] is False, result
    return result["content"][0]["text"], result["draft"]["dashboard"]


def test_nothing_is_preselected_from_the_chat_context(tmp_path):
    """'pass rate by device' must not collapse to the chat's current device (live finding, TASK-43 p9/10)."""
    text, dashboard = _draft_text_and_dashboard(tmp_path, {
        "_context_host_name": "host-1", "_context_device_id": "device1", "_context_userinterface_name": "stb_tv",
        "_context_workspace_id": "ws-1"})
    assert "Preselected filters: none." in text and "Every variable starts on All" in text
    assert "preselected to the current context" not in text.replace("do not say any filter was preselected to the current context", "")
    sql = json.dumps([p["targets"] for p in dashboard["panels"]])
    assert "host-1" not in sql and "device1" not in sql
    for name in ("host", "device_name", "user_interface", "environment", "flag"):
        variable = next((v for v in dashboard["templating"]["list"] if v["name"] == name), None)
        if variable:
            assert "$__all" in json.dumps(variable["current"]) or variable["current"].get("value") in ("$__all", ["$__all"]), (name, variable["current"])


def test_named_devices_are_preselected_and_current_device_scope_is_reported(tmp_path):
    text, _ = _draft_text_and_dashboard(tmp_path, {"_context_named_devices": [{"name": "Pixel 7", "host_name": "h", "on_server": True}]})
    assert "Device=Pixel 7" in text and "Filtered to the devices you named: Pixel 7" in text


def test_docker_file_provisioning_never_sees_the_template():
    for path in ("setup/docker/docker-compose.yml", "setup/docker/hetzner_custom/setup.sh"):
        text = (ROOT / path).read_text()
        assert "/dev/null:/var/lib/grafana/dashboards/template.json:ro" in text, path


# ------------------------------------------------------------------ drafts are built from the render's resolved requests
KPI_PANEL = {"preset": "kpi_radar", "title": "KPI radar"}
OTHER_PANEL = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate"], "mark": "bar"}


def _rendering_tools(tmp_path, api=None, rows_for=None):
    """Real render (resolution included) over a stubbed database."""
    tools = analytics_tools.AnalyticsTools()
    tools.service.api = api

    def query(request, context):
        source = tools.service._source(request["source_id"])
        fields = list(request.get("dimensions") or []) + list(request.get("metrics") or [])
        return {"model": "analytics-tabular-v1", "source_id": source.id, "fields": fields, "rows": [],
                "row_count": 0, "truncated": False, "units": {}, "time_grain": request.get("time_grain")}
    tools.service.query = query
    tools.service._run_query = lambda pick, context, source: {"rows": [{"userinterface_name": "stb_tv"}]}
    tools.drafts = _service(tmp_path)
    tools.publisher = RecordingPublisher()
    return tools


def test_canvas_draft_gets_the_defaulted_kpi_interface(tmp_path):
    tools = _rendering_tools(tmp_path)  # no interface in the request, none in the conversation
    result = tools.render_analytics_artifact({"panels": [KPI_PANEL, OTHER_PANEL], "_context_team_id": TEAM})
    assert "Grafana draft not created" not in result["content"][0]["text"]
    sent = tools.publisher.calls[0]
    assert sent["panels"][0]["filters"]["userinterface_name"] == "stb_tv" and "preset" in sent["panels"][0]
    # the primary builds it with a plain service: no context, no default lookup, same SQL as the render resolved
    built = _service(tmp_path).build(sent, CTX)
    assert sent["panels"][0]["filter_origin"]["userinterface_name"] == "defaulted"
    # BUG-0396: a defaulted interface is literal in its own panel; the variable stays All for the others
    assert "'stb_tv'" in _sql(built["dashboard"], 0)
    assert built["validation"]["errors"] == []
    current = {v["name"]: v["current"] for v in built["dashboard"]["templating"]["list"]}
    assert current["user_interface"]["value"] == ["$__all"]


def test_forwarded_draft_resolves_current_device_without_a_registry(tmp_path):
    from tests.backend_server.test_atlas_analytics import FakeRegistry
    params = {"panels": [OTHER_PANEL, {**OTHER_PANEL, "metrics": ["run_count"]}], "scope": "current_device",
              "_context_team_id": TEAM, "_context_host_name": "host-a", "_context_device_id": "device1"}
    tools = _rendering_tools(tmp_path, api=FakeRegistry())
    tools.render_analytics_artifact(params)
    sent, context = tools.publisher.calls[0], tools.publisher.contexts[0]
    assert context.device_name == "living-room-stb" and all(p["scope"] == "current_device" for p in sent["panels"])
    # main has no registry: it still builds because the originating server resolved the device
    main = _service(tmp_path)
    assert main.analytics.api is None
    built = main.build(sent, context)
    variables = {v["name"]: v for v in built["dashboard"]["templating"]["list"]}
    # BUG-0410: the user-origin scope is the device_name variable selection, not a literal clause
    assert "living-room-stb" in json.dumps(variables["device_name"]["current"]) and built["validation"]["errors"] == []
    with pytest.raises(AnalyticsValidationError, match="registry is unavailable"):
        main.build(sent, AnalyticsContext(team_id=TEAM, host_name="host-a", device_id="device1"))


def test_named_device_filter_is_carried_into_the_draft(tmp_path):
    tools = _rendering_tools(tmp_path)
    tools.render_analytics_artifact({"panels": [OTHER_PANEL, KPI_PANEL], "filters": {"device_name": ["Pixel 7"]},
                                     "_context_team_id": TEAM})
    sent = tools.publisher.calls[0]
    assert all(p["filters"]["device_name"] == ["Pixel 7"] for p in sent["panels"])
    built = _service(tmp_path).build(sent, CTX)
    current = {v["name"]: v["current"] for v in built["dashboard"]["templating"]["list"]}
    assert current["device_name"]["value"] == ["Pixel 7"]


def test_create_grafana_draft_resolves_presets_like_the_render(tmp_path):
    tools = _rendering_tools(tmp_path)
    result = tools.create_grafana_draft({"title": "K", "panels": [KPI_PANEL, OTHER_PANEL], "_context_team_id": TEAM})
    assert result["isError"] is False and "not pushed" not in result["content"][0]["text"]
    assert tools.publisher.calls[0]["panels"][0]["filters"]["userinterface_name"] == "stb_tv"


def test_draft_failure_notes_are_short_and_user_facing(tmp_path):
    tools = _rendering_tools(tmp_path)
    tools.publisher = RecordingPublisher(exc=AnalyticsValidationError(
        "Missing preset filters: ['userinterface_name']. Do not ask the user for them. Either pass a value"))
    result = tools.render_analytics_artifact({"panels": [KPI_PANEL, OTHER_PANEL], "_context_team_id": TEAM})
    text = result["content"][0]["text"]
    assert "Grafana draft not created: missing required filter: ['userinterface_name']" in text
    assert "Missing preset filters" not in text and "Do not ask" not in text


def _interpolate_like_grafana(sql, variables):
    """Grafana's substitution for these variables: a custom allValue is inserted RAW; selected values are
    single-quoted and comma-joined (sqlstring)."""
    import re as _re
    def sub(match):
        name = match.group(1) or match.group(2)
        if name not in variables:
            return match.group(0)
        value = variables[name]
        return value if isinstance(value, str) else ",".join("'" + v.replace("'", "''") + "'" for v in value)
    return _re.sub(r"\$\{(\w+)\}|\$(?!__)(\w+)", sub, sql)


def test_all_value_interpolates_to_valid_sql(tmp_path):
    """BUG-0385: allValue __all was inserted unquoted, so every panel on All read '__all' IN (__all) and
    Grafana answered: column "__all" does not exist."""
    built = _service(tmp_path).build({"title": "T", "panels": [PASS_BY_DEVICE, PASS_OVER_TIME]}, CTX)
    template = {v["name"]: v for v in built["dashboard"]["templating"]["list"]}
    on_all = {name: template[name]["allValue"] for name in ("host", "device_name", "user_interface", "environment")}
    for index in (0, 1):
        sql = _interpolate_like_grafana(_sql(built["dashboard"], index), on_all)
        assert "'__all' IN ('__all')" in sql
        assert not __import__("re").search(r"(?<!')__all(?!')", sql), sql
    picked = _interpolate_like_grafana(_sql(built["dashboard"]), {"host": ["vpt-pi1"], "device_name": ["S21x", "stb3"]})
    assert "'__all' IN ('vpt-pi1')" in picked and "IN ('S21x','stb3')" in picked
