"""Ephemeral Grafana drafts: catalog reuse, validation, provenance, containment and no promotion."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import AnalyticsContext, AnalyticsService  # noqa: E402
from backend_server.src.lib.analytics.grafana_drafts import (  # noqa: E402
    DATASOURCE, MAINTAINED_DASHBOARDS, GrafanaBinder, GrafanaDraftService,
)
from backend_server.src.lib.analytics.service import AnalyticsValidationError  # noqa: E402

TEAM = "00000000-0000-0000-0000-000000000123"
CTX = AnalyticsContext(team_id=TEAM, user_id="user-1", user_email="viewer@example.test", user_role="viewer")
ADMIN = AnalyticsContext(team_id=TEAM, user_id="admin-1", user_email="admin@example.test", user_role="admin")
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
DYNAMIC = {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["failure_count", "run_count"],
           "mark": "bar", "title": "Failures by device"}


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def drafts(tmp_path):
    return GrafanaDraftService(AnalyticsService(dsn="unused"), root=tmp_path / "tmp" / "atlas-grafana")


@pytest.fixture
def literal_drafts(tmp_path):
    """A missing template file: the built-in skeleton, no variables to bind filters to (literals inline)."""
    return GrafanaDraftService(AnalyticsService(dsn="unused"), root=tmp_path / "tmp" / "atlas-grafana",
                               template_path=tmp_path / "no-template.json")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Drafting must never reach Grafana or any other service."""
    def refuse(*args, **kwargs):
        raise AssertionError("Grafana drafts must not open network connections")
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_maintained_dashboard_is_reused_before_drafting(drafts):
    result = drafts.create({"preset": "campaign_pass_rate"}, CTX, now=NOW)
    assert result["status"] == "reused" and result["draft_path"] is None
    assert result["maintained"]["dashboard_file"].endswith("campaign-results.json")
    assert result["maintained"]["panel_title"] == "By Campaign"
    assert not drafts.root.exists() or not any(drafts.root.iterdir())
    # The same question asked dynamically (same fields) also finds the maintained panel.
    dynamic = {"source_id": "campaign_results", "dimensions": ["campaign_name"], "metrics": ["pass_rate", "run_count"]}
    assert drafts.create(dynamic, CTX, now=NOW)["status"] == "reused"


def test_prefer_existing_false_and_unmatched_requests_write_a_draft(drafts):
    result = drafts.create({"preset": "campaign_pass_rate", "prefer_existing": False}, CTX, now=NOW)
    assert result["status"] == "draft"
    result = drafts.create(DYNAMIC, CTX, now=NOW)
    assert result["status"] == "draft"
    path = drafts.root / result["request_id"]
    assert sorted(p.name for p in path.iterdir()) == ["dashboard.json", "draft.json"]
    assert result["draft_path"].endswith(f"{result['request_id']}/dashboard.json")


def test_draft_json_is_provisionable_and_uses_only_the_configured_datasource(drafts):
    result = drafts.create(DYNAMIC, CTX, now=NOW)
    dashboard = json.loads((drafts.root / result["request_id"] / "dashboard.json").read_text())
    assert "id" not in dashboard and dashboard["uid"].startswith("atlas-draft-") and len(dashboard["uid"]) <= 40
    assert dashboard["schemaVersion"] == 41 and dashboard["title"].startswith("[Draft] ")
    assert [v["name"] for v in dashboard["templating"]["list"]] == [
        "workspace", "allowed_devices", "host", "device_name", "user_interface", "environment", "flag"]
    datasources = []

    def walk(node):
        if isinstance(node, dict):
            if "datasource" in node:
                datasources.append(node["datasource"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(dashboard)
    assert datasources and all(ds == DATASOURCE for ds in datasources)
    panel = dashboard["panels"][0]
    assert panel["type"] == "barchart" and panel["targets"][0]["format"] == "table"
    assert result["validation"]["errors"] == []


def test_draft_sql_is_the_catalog_template_scoped_by_the_viewer(drafts):
    result = drafts.create(DYNAMIC, CTX, now=NOW)
    sql = result["dashboard"]["panels"][0]["targets"][0]["rawSql"]
    assert "grafana_device_scope(${__user.email:sqlstring}, ${__user.login:sqlstring}, ${workspace:sqlstring})" in sql
    assert "b AS (SELECT $__timeFrom()::timestamptz AS range_from, $__timeTo()::timestamptz AS range_to)" in sql
    assert f"(sr.team_id = '{TEAM}'::uuid)" in sql
    assert "COUNT(*) FILTER (WHERE NOT sr.success)" in sql
    assert ";" not in sql and "%s" not in sql
    metadata = json.loads((drafts.root / result["request_id"] / "draft.json").read_text())
    origin = metadata["panels"][0]
    assert origin["source_id"] == "script_results" and origin["query"]["metrics"] == ["failure_count", "run_count"]
    assert origin["sql_sha256"] == hashlib.sha256(sql.encode()).hexdigest()


def test_time_series_drafts_use_grafana_long_format(drafts):
    request = {"source_id": "script_results", "dimensions": ["time", "device_name"], "metrics": ["pass_rate"],
               "time_grain": "day", "mark": "line"}
    panel = drafts.create(request, CTX, now=NOW)["dashboard"]["panels"][0]
    assert panel["type"] == "timeseries" and panel["targets"][0]["format"] == "time_series"
    assert panel["targets"][0]["rawSql"].startswith('SELECT "time" AS "time", "device_name"::text AS "metric", "pass_rate" AS "value"')


def test_radar_and_plugin_marks_fall_back_to_core_panels(drafts):
    result = drafts.create({"preset": "kpi_radar", "filters": {"userinterface_name": "stb_tv"}}, CTX, now=NOW)
    assert result["status"] == "draft"
    assert result["dashboard"]["panels"][0]["type"] == "barchart"
    assert any("no core Grafana panel" in note for note in result["diagnostics"])


def test_multi_panel_draft_and_bounds(literal_drafts):
    drafts = literal_drafts
    panels = [{"preset": "pass_rate_trend"}, {"preset": "duration_trend"}, {"preset": "failing_testcases"}]
    result = drafts.create({"title": "Two devices", "panels": panels, "filters": {"device_name": ["a", "b"]}}, CTX, now=NOW)
    assert len(result["dashboard"]["panels"]) == 3
    assert all("ARRAY['a', 'b']::text[]" in p["targets"][0]["rawSql"] for p in result["dashboard"]["panels"])
    with pytest.raises(AnalyticsValidationError, match="1 to 6"):
        drafts.create({"panels": [DYNAMIC] * 7}, CTX, now=NOW)


def test_draft_literals_cannot_inject_sql_or_grafana_variables(drafts, literal_drafts):
    quoted = literal_drafts.create({**DYNAMIC, "filters": {"device_name": "o'brien"}}, CTX, now=NOW)
    assert "'o''brien'" in quoted["dashboard"]["panels"][0]["targets"][0]["rawSql"]
    for hostile in ("${__user.email}", "$__timeFilter(x)", "a\\'b", "line\nbreak"):
        with pytest.raises(AnalyticsValidationError, match="Draft filter values"):
            drafts.create({**DYNAMIC, "filters": {"device_name": hostile}}, CTX, now=NOW)
    with pytest.raises(AnalyticsValidationError, match="Unsupported fields"):
        drafts.create({**DYNAMIC, "metrics": ["1); DROP TABLE alerts; --"]}, CTX, now=NOW)
    binder = GrafanaBinder()
    assert binder.bind(["x", True, 3], "text[]") == "ARRAY['x', true, 3]::text[]"


def test_validation_rejects_tampering(drafts):
    result = drafts.create(DYNAMIC, CTX, now=NOW)
    metadata = json.loads((drafts.root / result["request_id"] / "draft.json").read_text())
    good = result["dashboard"]

    def errors(mutate):
        dashboard = json.loads(json.dumps(good))
        mutate(dashboard)
        return drafts.validate(dashboard, metadata, CTX)["errors"]

    assert errors(lambda d: None) == []
    assert any("not match its catalog template" in e for e in errors(
        lambda d: d["panels"][0]["targets"][0].__setitem__("rawSql", d["panels"][0]["targets"][0]["rawSql"].replace("NOT sr.success", "sr.success"))))
    assert any("non-read keyword" in e or "separator" in e for e in errors(
        lambda d: d["panels"][0]["targets"][0].__setitem__("rawSql", "SELECT 1; DELETE FROM alerts")))
    assert any("datasource" in e for e in errors(lambda d: d["panels"][0].__setitem__("datasource", {"uid": "other"})))
    assert any("credential-like" in e for e in errors(lambda d: d["panels"][0].__setitem__("secureJsonData", {"password": "x"})))
    assert any("core allowlisted panel" in e for e in errors(lambda d: d["panels"][0].__setitem__("type", "volkovlabs-echarts-panel")))
    assert any("must not carry an id" in e for e in errors(lambda d: d.__setitem__("id", 7)))
    assert any("template's variables" in e for e in errors(lambda d: d["templating"]["list"].append({"name": "x", "query": "SELECT 1"})))
    assert any("unexpected dashboard keys" in e for e in errors(lambda d: d.__setitem__("version", 3)))


def test_temp_path_containment(drafts, tmp_path):
    for bad in ("../escape-000", "a/b-00000000", "", "UPPER-CASE-123", "x" * 80, "..", "/etc/passwd"):
        with pytest.raises(AnalyticsValidationError):
            drafts._draft_dir(bad)
    assert drafts._draft_dir("abcdef12-20261003").parent == drafts.root
    with pytest.raises(AnalyticsValidationError, match="separate"):
        GrafanaDraftService(AnalyticsService(dsn="unused"), root=MAINTAINED_DASHBOARDS / "drafts")
    with pytest.raises(AnalyticsValidationError, match="separate"):
        GrafanaDraftService(AnalyticsService(dsn="unused"), root=tmp_path, maintained_dir=tmp_path / "dashboards")


def test_drafts_are_never_promoted_or_provisioned(drafts):
    before = _tree_digest(MAINTAINED_DASHBOARDS)
    provisioning = MAINTAINED_DASHBOARDS.parent / "config" / "provisioning"
    provisioning_before = _tree_digest(provisioning)
    result = drafts.create(DYNAMIC, CTX, now=NOW)
    assert _tree_digest(MAINTAINED_DASHBOARDS) == before
    assert _tree_digest(provisioning) == provisioning_before
    metadata = json.loads((drafts.root / result["request_id"] / "draft.json").read_text())
    assert metadata["provisioned"] is False and metadata["promotion"] == "manual"
    written = {str(p) for p in drafts.root.rglob("*") if p.is_file()}
    assert all(path.startswith(str(drafts.root)) for path in written)
    import backend_server.src.lib.analytics.grafana_drafts as module
    source = Path(module.__file__).read_text()
    assert "import requests" not in source and "urllib" not in source and "api/dashboards" not in source


def test_expiry_metadata_and_cleanup(drafts):
    result = drafts.create({**DYNAMIC, "ttl_hours": 2}, CTX, now=NOW)
    metadata = json.loads((drafts.root / result["request_id"] / "draft.json").read_text())
    assert datetime.fromisoformat(metadata["expires_at"]) == NOW + timedelta(hours=2)
    stray = drafts.root / "not-a-draft-dir"
    stray.mkdir()
    (stray / "notes.txt").write_text("keep me")
    assert drafts.cleanup_expired(NOW + timedelta(hours=1)) == 0
    assert drafts.cleanup_expired(NOW + timedelta(hours=3)) == 1
    assert not (drafts.root / result["request_id"]).exists()
    assert (stray / "notes.txt").exists()
    capped = drafts.create({**DYNAMIC, "ttl_hours": 10_000}, CTX, now=NOW)
    assert datetime.fromisoformat(capped["expires_at"]) == NOW + timedelta(days=7)


def test_admin_only_sources_stay_admin_only_in_drafts(drafts):
    with pytest.raises(AnalyticsValidationError, match="administrators"):
        drafts.create({"preset": "service_availability", "prefer_existing": False}, CTX, now=NOW)
    result = drafts.create({"preset": "service_availability", "prefer_existing": False}, ADMIN, now=NOW)
    assert result["status"] == "draft"
    assert "grafana_device_scope" not in result["dashboard"]["panels"][0]["targets"][0]["rawSql"]


def test_default_root_is_the_gitignored_tmp_folder():
    from backend_server.src.lib.analytics import grafana_drafts
    root = grafana_drafts.DRAFT_ROOT
    assert root.parts[-2:] == ("tmp", "atlas-grafana")
    gitignore = (grafana_drafts.PROJECT_ROOT / ".gitignore").read_text().splitlines()
    assert "tmp/" in gitignore
    assert not str(root).startswith(str(grafana_drafts.MAINTAINED_DASHBOARDS))
    assert os.path.isdir(grafana_drafts.MAINTAINED_DASHBOARDS)


def _override(panel, name):
    return next((o for o in panel["fieldConfig"]["overrides"] if o["matcher"]["options"] == name), None)


def _prop(override, prop_id):
    return next((p["value"] for p in override["properties"] if p["id"] == prop_id), None)


def test_bar_panel_hides_supporting_count_and_labels_rotate(drafts):
    draft = drafts.build({"preset": "pass_rate_by_device", "time_range_days": 7}, CTX, now=NOW)
    panel = draft["dashboard"]["panels"][0]
    assert panel["type"] == "barchart"
    assert _prop(_override(panel, "pass_rate"), "unit") == "percent"
    assert _override(panel, "pass_rate") and _prop(_override(panel, "pass_rate"), "custom.hideFrom") is None
    hidden = _prop(_override(panel, "run_count"), "custom.hideFrom")
    assert hidden["viz"] is True and hidden["legend"] is True and hidden["tooltip"] is False
    assert panel["fieldConfig"]["defaults"]["max"] == 100
    assert panel["options"]["xTickLabelRotation"] == -45 and panel["options"]["xTickLabelMaxLength"] == 18
    assert panel["options"]["tooltip"]["mode"] == "multi"


def test_few_categories_keep_labels_flat(drafts):
    draft = drafts.build({"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate"],
                          "mark": "bar", "limit": 5}, CTX, now=NOW)
    assert draft["dashboard"]["panels"][0]["options"]["xTickLabelRotation"] == 0


def test_table_columns_keep_their_own_units(drafts):
    draft = drafts.build({"source_id": "script_results", "dimensions": ["script_name"],
                          "metrics": ["avg_duration_ms", "run_count", "pass_rate"], "mark": "table"}, CTX, now=NOW)
    panel = draft["dashboard"]["panels"][0]
    assert panel["type"] == "table"
    assert _prop(_override(panel, "avg_duration_ms"), "unit") == "ms"
    assert _prop(_override(panel, "pass_rate"), "unit") == "percent"
    assert _override(panel, "run_count") is None
    assert not any(_prop(o, "custom.hideFrom") for o in panel["fieldConfig"]["overrides"])


def test_display_options_do_not_change_sql_provenance(drafts):
    draft = drafts.build({"preset": "pass_rate_by_device", "time_range_days": 7}, CTX, now=NOW)
    panel = draft["dashboard"]["panels"][0]
    origin = draft["metadata"]["panels"][0]
    assert hashlib.sha256(panel["targets"][0]["rawSql"].encode()).hexdigest() == origin["sql_sha256"]
    assert draft["validation"]["errors"] == []


# --------------------------------------------------------------------------- filter origin (BUG-0396)
CANVAS = {"title": "Week", "time_range_days": 7, "panels": [
    {"preset": "pass_rate_by_device"},
    {"preset": "kpi_slowest"},
]}


def _stub_query(service, monkeypatch, seen):
    """Render without a database: record the filters each panel's query ran with."""
    def query(request, context):
        seen.append(dict(request.get("filters") or {}))
        source = service._source(request["source_id"])
        fields = [f for f in list(request["dimensions"]) + list(request["metrics"])
                  if f in source.dimensions or f in source.metrics]
        return {"fields": fields, "rows": [], "truncated": False, "row_count": 0, "units": {}}
    monkeypatch.setattr(service, "query", query)


UI_CTX = AnalyticsContext(team_id=TEAM, user_id="u", user_email="v@example.test", user_role="viewer",
                          userinterface_name="web_tv")


def test_preset_defaults_stay_literal_and_variables_stay_all(drafts, monkeypatch):
    service = drafts.analytics
    context = AnalyticsContext(team_id=TEAM, user_id="u", user_email="v@example.test", user_role="viewer",
                               userinterface_name="web_tv")
    request, context = service.resolve_draft_request(CANVAS, context)
    by_title = {leaf["title"]: leaf for leaf in request["panels"]}
    kpi = by_title["Slowest KPIs"]
    assert kpi["filter_origin"] == {"environment": "preset_default", "userinterface_name": "defaulted"}  # success n/a
    assert "filter_origin" not in by_title["Pass rate by device"] or \
        "environment" not in by_title["Pass rate by device"]["filter_origin"]
    result = drafts.create(request, context, now=NOW)
    assert result["validation"]["errors"] == []
    dashboard = result["dashboard"]
    variables = {v["name"]: v for v in dashboard["templating"]["list"]}
    for name in ("user_interface", "environment"):
        assert variables[name]["current"]["value"] in (["$__all"], "$__all")  # untouched: All
    panels = {p["title"]: p for p in dashboard["panels"]}
    sql_kpi = panels["Slowest KPIs"]["targets"][0]["rawSql"]
    assert "'web_tv'" in sql_kpi and "'prod'" in sql_kpi            # literal in the KPI panel
    assert "Fixed for this panel" in panels["Slowest KPIs"]["description"]
    sql_pass = panels["Pass rate by device"]["targets"][0]["rawSql"]
    assert "'web_tv'" not in sql_pass and "'prod'" not in sql_pass  # the other panel is not narrowed
    assert "'__all' IN ($user_interface)" in sql_pass and "'__all' IN ($environment)" in sql_pass


def test_user_filters_still_become_variable_selections(drafts, monkeypatch):
    service = drafts.analytics
    canvas = {**CANVAS, "filters": {"environment": ["prod"]}}
    request, context = service.resolve_draft_request(canvas, UI_CTX)
    kpi = {leaf["title"]: leaf for leaf in request["panels"]}["Slowest KPIs"]
    assert kpi["filter_origin"] == {"userinterface_name": "defaulted"}
    assert "environment" in kpi["filters"] and kpi["filters"]["environment"] == ["prod"]
    result = drafts.create(request, context, now=NOW)
    assert result["validation"]["errors"] == []
    variables = {v["name"]: v for v in result["dashboard"]["templating"]["list"]}
    assert variables["environment"]["current"]["value"] in (["prod"], "prod")
    assert variables["user_interface"]["current"]["value"] in (["$__all"], "$__all")


def test_panel_only_filter_is_literal_but_named_device_is_a_variable(drafts):
    service = drafts.analytics
    canvas = {"panels": [{"preset": "pass_rate_by_device", "filters": {"environment": ["prod"], "device_name": ["tv1"]}},
                         {"preset": "pass_rate_by_script"}]}
    request, context = service.resolve_draft_request(canvas, CTX)
    first = request["panels"][0]
    assert first["filter_origin"]["environment"] == "panel" and "device_name" not in first["filter_origin"]
    result = drafts.create(request, context, now=NOW)
    variables = {v["name"]: v for v in result["dashboard"]["templating"]["list"]}
    assert variables["device_name"]["current"]["value"] in (["tv1"], "tv1")
    assert variables["environment"]["current"]["value"] in (["$__all"], "$__all")


def test_render_and_draft_run_the_same_filters_per_panel(drafts, monkeypatch):
    """Default view (variables on All): each draft panel filters exactly like the chat canvas panel."""
    service = drafts.analytics
    context = AnalyticsContext(team_id=TEAM, user_id="u", user_email="v@example.test", user_role="viewer",
                               userinterface_name="web_tv")
    seen = []
    _stub_query(service, monkeypatch, seen)
    artifact = service.render(CANVAS, context)
    render_filters = list(seen)
    spec = artifact["content_data"]["artifact_spec"]
    leaves = [p["provenance"]["resolved_request"] for p in spec["panels"]]
    result = drafts.create({"panels": leaves, "title": "Week"}, context, now=NOW)
    assert result["validation"]["errors"] == []
    variables = {v["name"]: v for v in result["dashboard"]["templating"]["list"]}
    assert all(v["current"]["value"] in (["$__all"], "$__all") for v in variables.values()
               if v["name"] in ("host", "device_name", "user_interface", "environment", "flag"))
    var_for = {"environment": "environment", "userinterface_name": "user_interface"}
    for panel, filters in zip(result["dashboard"]["panels"], render_filters):
        sql = panel["targets"][0]["rawSql"]
        for name in ("environment", "userinterface_name"):
            if name in filters:
                values = filters[name] if isinstance(filters[name], list) else [filters[name]]
                assert all(f"'{value}'" in sql for value in values), (panel["title"], name)
                assert f"IN (${var_for[name]})" not in sql, (panel["title"], name)
            else:
                assert f"'__all' IN (${var_for[name]})" in sql, (panel["title"], name)
        # no literal value appears that the chat panel did not filter on
        literal_values = {v for values in filters.values() for v in (values if isinstance(values, list) else [values])}
        assert ("'web_tv'" in sql) == ("web_tv" in literal_values)


DEV_CTX = AnalyticsContext(team_id=TEAM, user_id="u", user_email="v@example.test", user_role="viewer",
                           host_name="host-clone-1", device_id="device1", device_name="host-clone-1_Host")


def _variables(result):
    return {v["name"]: v for v in result["dashboard"]["templating"]["list"]}


def test_user_current_device_scope_becomes_host_and_device_variables(drafts):
    """BUG-0410: 'my selected devices' opens with host/device preselected, like a named device."""
    service = drafts.analytics
    canvas = {"scope": "current_device", "panels": [{"preset": "pass_rate_by_device"}, {"preset": "pass_rate_by_script"}]}
    request, context = service.resolve_draft_request(canvas, DEV_CTX)
    assert all("scope" not in (leaf.get("filter_origin") or {}) for leaf in request["panels"])
    result = drafts.create(request, context, now=NOW)
    assert result["validation"]["errors"] == []
    variables = _variables(result)
    assert variables["host"]["current"]["value"] in (["host-clone-1"], "host-clone-1")
    assert variables["device_name"]["current"]["value"] in (["host-clone-1_Host"], "host-clone-1_Host")
    for panel in result["dashboard"]["panels"]:
        sql = panel["targets"][0]["rawSql"]
        assert "IN ($host)" in sql and "IN ($device_name)" in sql
        assert "'host-clone-1'" not in sql and "'host-clone-1_Host'" not in sql  # bound, not literal
    for origin in result["metadata"]["panels"] if "metadata" in result else []:
        assert "scope" not in origin["query"]


def test_panel_only_current_device_scope_stays_literal(drafts):
    service = drafts.analytics
    canvas = {"panels": [{"preset": "pass_rate_by_device", "scope": "current_device"}, {"preset": "pass_rate_by_script"}]}
    request, context = service.resolve_draft_request(canvas, DEV_CTX)
    assert request["panels"][0]["filter_origin"]["scope"] == "panel"
    result = drafts.create(request, context, now=NOW)
    assert result["validation"]["errors"] == []
    variables = _variables(result)
    assert variables["host"]["current"]["value"] in (["$__all"], "$__all")
    assert variables["device_name"]["current"]["value"] in (["$__all"], "$__all")
    first = result["dashboard"]["panels"][0]["targets"][0]["rawSql"]
    assert "'host-clone-1'" in first and "'host-clone-1_Host'" in first


def test_named_device_draft_is_unchanged_by_scope_binding(drafts):
    service = drafts.analytics
    canvas = {"filters": {"host_name": ["host-clone-1"], "device_name": ["host-clone-1_Host"]},
              "panels": [{"preset": "pass_rate_by_device"}]}
    request, context = service.resolve_draft_request(canvas, DEV_CTX)
    result = drafts.create(request, context, now=NOW)
    variables = _variables(result)
    assert variables["host"]["current"]["value"] in (["host-clone-1"], "host-clone-1")
    assert variables["device_name"]["current"]["value"] in (["host-clone-1_Host"], "host-clone-1_Host")
