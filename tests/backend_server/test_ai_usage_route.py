"""TASK-87: GET /server/ai/usage, /usage/export, /usage/calls — query rules and aggregation (no DB, no auth)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend_server", "src"))

from backend_server.src.routes import server_ai_routing_routes as routes  # noqa: E402

NOW = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _row(**kw):
    base = {"bucket": NOW.isoformat(), "usage_key": "vision.banner", "team_id": "t1", "profile": "gpu",
            "endpoint": "lab", "split_arm": "", "origin": "script", "host_name": "h1", "device_id": "d1",
            "script_name": "zap", "campaign_id": "", "user_id": "u1", "server": "s1", "calls": 10, "errors": 1,
            "fallbacks": 0, "total_ms": 10000, "tokens_in": 1000, "tokens_out": 200, "cost": 0.5,
            "priced_calls": 10, "avoided": 0}
    base.update(kw)
    return base


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def call(monkeypatch):
    seen = {}
    rows = [_row(), _row(script_name="menu", user_id="u2", calls=4, errors=0, cost=0.1, priced_calls=4),
            _row(bucket=(NOW - timedelta(hours=30)).isoformat(), origin="monitoring", script_name="", user_id="")]
    monkeypatch.setattr(routes.ai_routing_db, "get_calls_rollup",
                        lambda *a, **k: seen.setdefault("calls", (a, k)) and rows)
    monkeypatch.setattr(routes.ai_routing_db, "get_usage_rows", lambda *a, **k: seen.setdefault("rollup", (a, k)) and rows)
    monkeypatch.setattr(routes.ai_routing_db, "get_skipped_paused", lambda *a, **k: {})
    monkeypatch.setattr(routes.ai_routing_db, "list_endpoints", lambda: [
        {"id": "e1", "name": "lab", "preset": "openai_compatible", "region": "local", "reach": "server"}])
    monkeypatch.setattr(routes.ai_routing_db, "get_user_names", lambda ids: {"u1": "Ada", "u2": "Bob"})
    monkeypatch.setattr(routes.ai_routing_db, "get_team_names", lambda ids: {"t1": "Team One"})
    monkeypatch.setattr(routes.router, "resolve", lambda *a, **k: (_ for _ in ()).throw(routes.router.AIRoutingError("x")))
    monkeypatch.setattr(routes, "_is_admin", lambda: False)
    monkeypatch.setattr(routes, "principal_holds_permission", lambda p: True)
    app = Flask("t")

    def run(fn, query, **ctx):
        with app.test_request_context("/x?" + query):
            routes.request.user_id = "u1"
            resp = _unwrap(fn)()
            return resp if isinstance(resp, tuple) else (resp, resp.status_code), seen
    return run


def test_group_by_user_uses_calls_and_names(call):
    (resp, status), seen = call(routes.get_usage, "team_id=t1&hours=24&group_by=user")
    body = resp.get_json()
    assert status == 200 and body["source"] == "calls" and "user" in body["groups"]
    assert {r["label"] for r in body["rows"]} == {"Ada", "Bob", "—"}
    assert seen["calls"][0][:2] == ("t1", 24)
    lab = body["providers"][0]
    assert lab["endpoint"] == "lab" and lab["region"] == "local" and lab["type"] == "local" and lab["status"] == "degraded"  # 1 of 10 failed
    assert len(lab["answered_series"]) == len(lab["failed_series"]) == body["series_len"] == 24
    assert body["previous"]["calls"] == 10  # the row 30 h ago and body["chart_hours"] == 24


def test_thirty_days_read_the_rollup_and_refuse_call_only_dimensions(call):
    (resp, status), seen = call(routes.get_usage, "team_id=t1&hours=720&group_by=usage")
    assert status == 200 and resp.get_json()["source"] == "rollup" and "rollup" in seen
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=720&group_by=user")
    assert status == 400
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=720&group_by=usage&filter_script=zap")
    assert status == 400


def test_filters_and_cost_totals(call):
    (resp, _), _ = call(routes.get_usage, "team_id=t1&hours=24&group_by=script&filter_origin=script")
    body = resp.get_json()
    assert {r["key"] for r in body["rows"]} == {"zap", "menu"}
    assert body["totals"]["cost"] == pytest.approx(0.6) and body["totals"]["calls"] == 14


def test_team_is_required_unless_admin_scope_all(call, monkeypatch):
    (resp, status), _ = call(routes.get_usage, "hours=24")
    assert status == 400
    monkeypatch.setattr(routes, "_is_admin", lambda: True)
    (resp, status), seen = call(routes.get_usage, "hours=24&scope=all")
    assert status == 200 and seen["calls"][0][2] is True  # all_teams reached the query


def test_user_without_models_permission_only_sees_own_calls(call, monkeypatch):
    monkeypatch.setattr(routes, "principal_holds_permission", lambda p: False)
    (resp, status), seen = call(routes.get_usage, "team_id=t1&hours=24&group_by=usage")
    assert status == 200 and seen["calls"][1].get("user_id", seen["calls"][0][-1]) == "u1"
    assert resp.get_json()["restricted_to_self"] is True and resp.get_json()["providers"] == []
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=720&group_by=usage")
    assert status == 400


def test_bad_arguments(call):
    assert call(routes.get_usage, "team_id=t1&hours=5")[0][1] == 400
    assert call(routes.get_usage, "team_id=t1&hours=24&group_by=nope")[0][1] == 400


def test_csv_export_has_a_total_row(call):
    (resp, status), _ = call(routes.export_usage, "team_id=t1&hours=24&group_by=script")
    text = resp.get_data(as_text=True)
    assert status == 200 and resp.mimetype == "text/csv"
    lines = text.strip().splitlines()
    assert lines[0].startswith("script,name,calls,errors") and lines[-1].startswith("TOTAL,")
    assert any(line.startswith("zap,") for line in lines)


def test_run_cost_needs_team_and_ids(call, monkeypatch):
    monkeypatch.setattr(routes.ai_routing_db, "get_run_cost",
                        lambda team, ids: {"calls": len(ids), "cost": 0.25, "errors": 0, "tokens_in": 1, "tokens_out": 1,
                                           "priced_calls": 1})
    (resp, status), _ = call(routes.usage_run, "team_id=t1&script_result_ids=a,b,")
    assert status == 200 and resp.get_json()["calls"] == 2 and resp.get_json()["cost"] == 0.25
    assert call(routes.usage_run, "team_id=t1")[0][1] == 400
    assert call(routes.usage_run, "script_result_ids=a")[0][1] == 400


def test_price_validation(call, monkeypatch):
    monkeypatch.setattr(routes.ai_routing_db, "list_endpoints", lambda: [{"name": "lab"}])
    ok = {"endpoint": "lab", "model": "*", "price_in": 0, "price_out": 0}
    assert routes._validate_price(ok) is None  # a price of 0 is a real price (local GPU)
    assert routes._validate_price({**ok, "endpoint": "nope"})
    assert routes._validate_price({**ok, "model": " "})
    assert routes._validate_price({**ok, "price_in": -1})
    assert routes._validate_price({**ok, "price_out": True})
    assert routes._validate_price({**ok, "price_cache_read": "x"})
    assert routes._validate_price({**ok, "valid_from": "yesterday"})
    assert routes._validate_price({**ok, "valid_from": "2026-10-12T00:00:00Z", "price_cache_read": 0.3}) is None


def test_alerts_route_groups_failures_by_cause_with_named_provider(call, monkeypatch):
    now = datetime.now(timezone.utc)
    stamp = {"bucket": now.replace(minute=0, second=0, microsecond=0).isoformat(),
             "first_ts": (now - timedelta(minutes=40)).isoformat(), "last_ts": (now - timedelta(minutes=2)).isoformat()}
    rows = [{"usage_key": "agent.browser", "calls": 3, "errors": 3, "fallbacks": 0, "endpoint": "or",
             "error_type": "no_credit", **stamp},
            {"usage_key": "text.decision.localize", "calls": 40, "errors": 40, "fallbacks": 0, "endpoint": "or",
             "error_type": "no_credit", **stamp}]
    monkeypatch.setattr(routes.ai_routing_db, "get_calls_rollup", lambda *a, **k: rows)
    monkeypatch.setattr(routes.ai_routing_db, "list_endpoints",
                        lambda: [{"id": "e", "name": "or", "preset": "openrouter", "reach": "server"}])
    monkeypatch.setattr(routes.ai_routing_db, "get_skipped_paused", lambda *a, **k: {"or": [stamp["last_ts"]] * 5})
    (resp, status), _ = call(routes.usage_alerts, "team_id=t1")
    body = resp.get_json()
    assert status == 200 and len(body["causes"]) == 1 and body["thresholds"]["error_rate"] == 0.05
    cause = body["causes"][0]
    assert (cause["provider"], cause["type"], cause["reason"], cause["severity"]) == ("or", "cloud", "no_credit", "error")
    assert [f["label"] for f in cause["features"]] == ["Localize second opinion", "Browser agent"]
    assert cause["skipped"] == 5
    assert call(routes.usage_alerts, "")[0][1] == 400


def test_budget_validation_and_status(call, monkeypatch):
    saved = {}
    monkeypatch.setattr(routes.ai_routing_db, "set_budget", lambda *a: saved.update(args=a))
    monkeypatch.setattr(routes.ai_routing_db, "get_month_spend", lambda team, since: 10.0)
    monkeypatch.setattr(routes.ai_routing_db, "get_budget", lambda team: {"month_limit_usd": 100, "mode": "block", "warn_at": 0.8})

    def put(body):
        from flask import Flask
        app = Flask("b")
        with app.test_request_context("/x", method="PUT", json=body):
            routes.request.user_id = "admin-1"
            resp = _unwrap(routes.set_budget)()
            return resp if isinstance(resp, tuple) else (resp, resp.status_code)

    assert put({"team_id": "t1", "month_limit_usd": 50, "mode": "block"})[1] == 200
    assert saved["args"] == ("t1", 50, "block", 0.8, "admin-1")
    for bad in ({"month_limit_usd": 50}, {"team_id": "t1", "month_limit_usd": 0}, {"team_id": "t1", "month_limit_usd": 5, "mode": "kill"},
                {"team_id": "t1", "month_limit_usd": 5, "warn_at": 2}, {"team_id": "t1", "month_limit_usd": True}):
        assert put(bad)[1] == 400
    (resp, status), _ = call(routes.usage_budget, "team_id=t1")
    body = resp.get_json()
    assert status == 200 and body["spent"] == 10.0 and body["budget"]["mode"] == "block" and body["budget"]["limit"] == 100


def test_round_two_fields_overview_options_errors_and_new_filters(call, monkeypatch):
    monkeypatch.setattr(routes.workspaces_db, "get_user_workspaces", lambda uid: [{"id": "w1", "name": "Lab"}])
    monkeypatch.setattr(routes, "_caller_team_ids", lambda: {"t1"})
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=24&group_by=category_caller")
    body = resp.get_json()
    assert status == 200 and body["rows"][0]["key"].startswith("screen_recognition|")
    ov = body["overview"]
    assert ov["categories"][0]["key"] == "screen_recognition" and ov["totals"]["wasted"] == 2
    assert {c["key"] for c in ov["callers"]} >= {"script:zap", "script:menu"}
    assert [t["label"] for t in body["options"]["team"]] == ["Team One"] or body["options"]["team"] == []
    assert {u["label"] for u in body["options"]["user"]} >= {"Ada", "Bob"}
    assert body["options"]["project"] == [{"key": "w1", "label": "Lab"}]
    assert body["errors"]["count"] == len(body["errors"]["causes"])
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=24&filter_result=failed&filter_category=screen_recognition")
    assert status == 200 and resp.get_json()["totals"]["calls"] == 20  # the two rows of the fixture that carry failures
    (resp, status), _ = call(routes.get_usage, "team_id=t1&hours=720&filter_result=failed")
    assert status == 400  # the 30-day rollup cannot split answered from failed


def test_settings_scope_all_lists_every_layer_and_refuses_foreign_teams(call, monkeypatch):
    monkeypatch.setattr(routes, "_caller_team_ids", lambda: {"t1"})
    monkeypatch.setattr(routes.ai_routing_db, "list_endpoints", lambda: [])
    monkeypatch.setattr(routes.ai_routing_db, "list_profiles", lambda: [])
    monkeypatch.setattr(routes.ai_routing_db, "list_routes_all", lambda: [
        {"id": "r0", "team_id": None, "usage_key": "vision"}, {"id": "r1", "team_id": "t1", "usage_key": "vision"},
        {"id": "r2", "team_id": "t2", "usage_key": "vision"}])
    monkeypatch.setattr(routes, "_effective", lambda *a, **k: {})
    monkeypatch.setattr(routes, "_scope_options", lambda: {"team": [], "project": []})
    (resp, status), _ = call(routes.get_config, "scope_team=all")
    body = resp.get_json()
    assert status == 200 and [r["id"] for r in body["routes"]] == ["r0", "r1"] and body["scope"]["team"] == "all"
    (resp, status), _ = call(routes.get_config, "scope_team=t2")
    assert status == 403
