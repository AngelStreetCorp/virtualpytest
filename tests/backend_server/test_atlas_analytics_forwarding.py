"""A backend server without a database connection forwards the SQL half of analytics.

Observed live: chatting through the Pi-hosted server, every analytics call failed with
"Analytics datasource is not configured" — that server reaches the database only through
the Supabase API.
"""

from __future__ import annotations

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import service as service_module  # noqa: E402
from backend_server.src.lib.analytics.service import (  # noqa: E402
    AnalyticsContext, AnalyticsService, AnalyticsValidationError, RemoteAnalytics,
)
from backend_server.src.routes import server_atlas_analytics_routes as routes  # noqa: E402

TEAM = "00000000-0000-0000-0000-000000000123"
CTX = AnalyticsContext(team_id=TEAM, user_id="user-1", user_email="viewer@example.test", user_role="viewer",
                       workspace_id="ws-1", host_name="host-a", device_id="device1")
ROWS = [{"device_name": "living-room-stb", "pass_rate": 92.5, "run_count": 40}]


class Registry:
    def get(self, path, params=None):
        return {"hosts": [{"host_name": "host-a", "devices": [{"device_id": "device1", "device_name": "living-room-stb"}]}]}


class RecordingRemote(RemoteAnalytics):
    def __init__(self, reply):
        super().__init__("https://primary.example.test", "key")
        self.calls, self.reply = [], reply

    def call(self, operation, payload):
        self.calls.append((operation, payload))
        return self.reply(operation, payload)


def test_remote_is_configured_from_env(monkeypatch):
    monkeypatch.setenv("API_KEY", "service-key")
    monkeypatch.delenv("ANALYTICS_FORWARD_URL", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://vpt.example.test/supabase")
    remote = RemoteAnalytics.from_env()
    assert remote.base_url == "https://vpt.example.test" and remote.api_key == "service-key"
    monkeypatch.setenv("ANALYTICS_FORWARD_URL", "https://primary.example.test/")
    assert RemoteAnalytics.from_env().base_url == "https://primary.example.test"
    monkeypatch.delenv("ANALYTICS_FORWARD_URL")
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    assert RemoteAnalytics.from_env() is None
    monkeypatch.setenv("ANALYTICS_FORWARD_URL", "https://primary.example.test")
    monkeypatch.delenv("API_KEY")
    assert RemoteAnalytics.from_env() is None


def test_a_server_with_a_datasource_never_forwards(monkeypatch):
    monkeypatch.setenv("API_KEY", "service-key")
    monkeypatch.setenv("ANALYTICS_FORWARD_URL", "https://primary.example.test")
    assert AnalyticsService(dsn="postgresql://readonly@db/x").remote is None


def test_query_forwards_and_resolves_the_current_device_locally():
    remote = RecordingRemote(lambda op, payload: {"model": "analytics-tabular-v1", "source_id": "script_results",
                                                  "fields": ["device_name", "pass_rate", "run_count"], "rows": ROWS,
                                                  "row_count": 1, "truncated": False, "units": {}, "time_grain": None})
    service = AnalyticsService(dsn="", api_client=Registry(), remote=remote)
    service.dsn = ""
    spec = service.render({"preset": "pass_rate_by_device", "scope": "current_device"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "bar" and spec["data"]["rows"] == ROWS
    operation, payload = remote.calls[0]
    assert operation == "query"
    assert payload["context"]["team_id"] == TEAM and payload["context"]["device_name"] == "living-room-stb"
    assert payload["request"]["source_id"] == "script_results" and "preset" not in payload["request"]
    assert AnalyticsContext.from_dict(payload["context"]).device_name == "living-room-stb"


def test_live_scope_for_non_admins_is_forwarded():
    remote = RecordingRemote(lambda op, payload: ["host-a:device1"])
    service = AnalyticsService(dsn="", api_client=Registry(), remote=remote)
    service.dsn = ""
    rows = service.query({"source_id": "live_system_status"}, CTX)["rows"]
    assert [row["device_name"] for row in rows] == ["living-room-stb"]
    assert remote.calls[0][0] == "device-scope"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "service-key")
    app = Flask(__name__)
    app.register_blueprint(routes.server_atlas_analytics_bp)
    monkeypatch.setattr(routes, "_team_ids_from_db", lambda user_id: {TEAM} if user_id == "user-1" else set())
    return app.test_client()


def _post(client, path, body, key="service-key"):
    return client.post(f"/server/atlas-analytics/{path}", json=body, headers={"X-API-Key": key} if key else {})


def test_route_accepts_only_the_service_key_and_rechecks_the_team(client, monkeypatch):
    monkeypatch.setattr(service_module.AnalyticsService, "query", lambda self, request, context: {"rows": ROWS})
    monkeypatch.setenv("SUPABASE_DB_URI", "postgresql://readonly@db/x")
    body = {"request": {"source_id": "script_results"}, "context": CTX.as_dict()}
    assert _post(client, "query", body, key=None).status_code == 403
    assert _post(client, "query", body, key="wrong").status_code == 403
    other_team = {**body, "context": {**CTX.as_dict(), "team_id": "00000000-0000-0000-0000-000000000999"}}
    assert _post(client, "query", other_team).status_code == 403
    assert _post(client, "query", {**body, "context": {}}).status_code == 400
    response = _post(client, "query", body)
    assert response.status_code == 200 and response.get_json()["result"] == {"rows": ROWS}
    # Live: the auto-sign test login is user "auto_sign", which has no membership rows.
    shared = {**body, "context": {**CTX.as_dict(), "user_id": "auto_sign"}}
    assert _post(client, "query", shared).status_code == 200
    stranger = {**body, "context": {**CTX.as_dict(), "user_id": "00000000-0000-0000-0000-00000000dead"}}
    assert _post(client, "query", stranger).status_code == 403


def test_route_refuses_to_forward_again_and_reports_validation_errors(client, monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URI", raising=False)
    monkeypatch.delenv("ANALYTICS_DB_URI", raising=False)
    body = {"request": {"source_id": "script_results"}, "context": CTX.as_dict()}
    response = _post(client, "query", body)
    assert response.status_code == 400 and "not configured on this server" in response.get_json()["error"]
    monkeypatch.setenv("SUPABASE_DB_URI", "postgresql://readonly@db/x")
    response = _post(client, "query", {**body, "request": {"source_id": "pg_shadow"}})
    assert response.status_code == 400 and response.get_json()["error"].startswith("Unknown analytics source: 'pg_shadow'. Valid source ids:")


def test_forwarding_end_to_end_through_the_route(client, monkeypatch):
    """A datasource-less server renders a chart through the primary server's real route."""
    monkeypatch.setenv("SUPABASE_DB_URI", "postgresql://readonly@db/x")
    seen = {}

    def primary_query(self, request, context):
        seen["context"] = context
        sql, values, fields = self.build_query(request, context)
        seen["sql"] = sql
        return {"model": "analytics-tabular-v1", "source_id": request["source_id"], "fields": fields, "rows": ROWS,
                "row_count": 1, "truncated": False, "units": {}, "time_grain": None}

    class RouteRemote(RemoteAnalytics):
        def call(self, operation, payload):
            response = _post(client, operation, payload)
            body = response.get_json()
            if response.status_code == 400:
                raise AnalyticsValidationError(body["error"])
            assert response.status_code == 200
            return body["result"]

    monkeypatch.setattr(routes, "AnalyticsService", lambda: type("Primary", (), {
        "dsn": "postgresql://readonly@db/x",
        "query": lambda _self, request, context: primary_query(AnalyticsService(dsn="unused"), request, context)})())
    edge = AnalyticsService(dsn="", api_client=Registry(), remote=RouteRemote("https://primary", "service-key"))
    edge.dsn = ""
    spec = edge.render({"preset": "failing_testcases", "scope": "current_device"}, CTX)["content_data"]["artifact_spec"]
    assert spec["mark"] == "table"
    assert seen["context"].device_name == "living-room-stb" and seen["context"].team_id == TEAM
    assert "(sr.team_id = %s::uuid)" in seen["sql"] and "sr.device_name = %s::text" in seen["sql"]
