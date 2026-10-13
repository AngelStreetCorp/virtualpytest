"""Automatic Grafana drafts for Atlas canvases: push, cleanup, dedupe, forwarding, failure isolation.

No network: Grafana is a fake HTTP client.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

from backend_server.src.lib.analytics import AnalyticsContext, AnalyticsService  # noqa: E402
from backend_server.src.lib.analytics import grafana_push  # noqa: E402
from backend_server.src.lib.analytics.grafana_drafts import GrafanaDraftService  # noqa: E402
from backend_server.src.lib.analytics.grafana_push import (  # noqa: E402
    FOLDER_UID, GrafanaClient, GrafanaDraftPublisher, GrafanaPushError, cleanup_expired,
)
from backend_server.src.lib.analytics.service import AnalyticsValidationError, RemoteAnalytics  # noqa: E402
from backend_server.src.mcp.tools import analytics_tools  # noqa: E402
from backend_server.src.routes import server_atlas_analytics_routes as routes  # noqa: E402

TEAM = "00000000-0000-0000-0000-000000000123"
CTX = AnalyticsContext(team_id=TEAM, user_id="user-1", user_email="viewer@example.test", workspace_id="ws-1")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
CANVAS = {"title": "Pass rate and failures", "panels": [
    {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["pass_rate", "run_count"], "mark": "bar"},
    {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["failure_count"], "mark": "bar"}]}


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body

    @property
    def content(self):
        return b"x" if self._body is not None else b""

    def json(self):
        return self._body


class FakeHttp:
    """Just enough Grafana: folders, dashboards, search."""

    def __init__(self):
        self.folder = None
        self.dashboards = {}
        self.calls = []
        self.fail_push = False

    def _record(self, method, url, **kw):
        self.calls.append((method, url.split(":3000/grafana", 1)[-1], kw))
        assert kw["auth"] == ("admin", "pw") and kw["timeout"] <= 10

    def get(self, url, **kw):
        self._record("get", url, **kw)
        if "/api/folders/" in url:
            return Response(200, {"uid": FOLDER_UID}) if self.folder else Response(404, {})
        if url.endswith("/api/search"):
            return Response(200, [{"uid": uid, "tags": d["dashboard"]["tags"], "folderUid": d["folderUid"]}
                                  for uid, d in self.dashboards.items()])
        raise AssertionError(url)

    def post(self, url, **kw):
        self._record("post", url, **kw)
        if url.endswith("/api/folders"):
            self.folder = kw["json"]
            return Response(200, {})
        if url.endswith("/permissions"):
            self.permissions = kw["json"]
            return Response(200, {})
        if url.endswith("/api/dashboards/db"):
            if self.fail_push:
                return Response(500, {})
            self.dashboards[kw["json"]["dashboard"]["uid"]] = kw["json"]
            return Response(200, {"status": "success"})
        raise AssertionError(url)

    def delete(self, url, **kw):
        self._record("delete", url, **kw)
        self.dashboards.pop(url.rsplit("/", 1)[-1], None)
        return Response(200, {})


@pytest.fixture(autouse=True)
def grafana_env(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "http://grafana.internal:3000/grafana")
    monkeypatch.setenv("GRAFANA_ADMIN_USER", "admin")
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("GRAFANA_DOMAIN", "vpt.example.test")

    def refuse(*args, **kwargs):
        raise AssertionError("no real network")
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def http():
    return FakeHttp()


@pytest.fixture
def publisher(http, tmp_path):
    analytics = AnalyticsService(dsn="unused")
    return GrafanaDraftPublisher(analytics, GrafanaDraftService(analytics, root=tmp_path / "tmp" / "atlas-grafana"),
                                 GrafanaClient(http))


def test_push_creates_folder_and_pushes_validated_dashboard(publisher, http):
    result = publisher.publish(CANVAS, CTX, NOW)
    assert result["reused"] is False and result["uid"].startswith("atlas-draft-") and len(result["uid"]) <= 40
    # A server-independent path (the web app knows the public Grafana host); never GRAFANA_DOMAIN
    # (the marketing website on main) and never the internal GRAFANA_URL. Carries the active workspace.
    assert result["path"] == f"/grafana/d/{result['uid']}?var-workspace=ws-1" and "url" not in result
    assert "grafana.internal" not in json.dumps(result) and "vpt.example.test" not in json.dumps(result)
    assert http.folder == {"uid": FOLDER_UID, "title": "Atlas drafts"}
    assert {"role": "Viewer", "permission": 1} in http.permissions["items"] and all(i["permission"] == 1 for i in http.permissions["items"])
    pushed = http.dashboards[result["uid"]]
    assert pushed["folderUid"] == FOLDER_UID and pushed["overwrite"] is True
    dashboard = pushed["dashboard"]
    assert "id" not in dashboard and dashboard["tags"][0] == "atlas-draft"
    expires = int((NOW + timedelta(hours=24)).timestamp())
    assert dashboard["tags"][1] == f"atlas-expires-{expires}"
    assert len(dashboard["panels"]) == 2
    assert json.dumps(dashboard).count('"uid": "supabase-postgres"') >= 4
    assert result["expires_at"] == (NOW + timedelta(hours=24)).isoformat()


def test_validation_runs_before_any_http_call(publisher, http, monkeypatch):
    monkeypatch.setattr(GrafanaDraftService, "validate", lambda self, d, m, c: {"errors": ["forced"], "checks": []})
    with pytest.raises(AnalyticsValidationError, match="forced"):
        publisher.publish(CANVAS, CTX, NOW)
    assert http.calls == [] and http.dashboards == {}


def test_tampered_sql_is_never_pushed(publisher, http, monkeypatch):
    original = GrafanaDraftService.build

    def tampered(self, *a, **k):
        built = original(self, *a, **k)
        built["dashboard"]["panels"][0]["targets"][0]["rawSql"] += " UNION SELECT 1"
        return built
    monkeypatch.setattr(GrafanaDraftService, "build", tampered)
    with pytest.raises(AnalyticsValidationError):
        publisher.publish(CANVAS, CTX, NOW)
    assert http.dashboards == {}


def test_same_canvas_reuses_the_uid_and_overwrites(publisher, http):
    first = publisher.publish(CANVAS, CTX, NOW)
    second = publisher.publish(CANVAS, CTX, NOW + timedelta(minutes=5))
    assert first["uid"] == second["uid"] and len(http.dashboards) == 1
    other = publisher.publish({**CANVAS, "title": "Different"}, CTX, NOW)
    assert other["uid"] != first["uid"]
    stranger = AnalyticsContext(team_id=TEAM, user_id="user-2")
    assert publisher.publish(CANVAS, stranger, NOW)["uid"] != first["uid"]
    assert sum(1 for c in http.calls if c[0] == "post" and c[1] == "/api/folders") == 1  # folder created once


def test_all_maintained_panels_link_the_maintained_dashboard_without_pushing(publisher, http):
    result = publisher.publish({"panels": [{"preset": "campaign_pass_rate"}, {"preset": "campaign_pass_rate"}]}, CTX, NOW)
    assert result["reused"] is True and result["expires_at"] is None
    assert result["path"].startswith("/grafana/d/") and not http.calls
    # One maintained panel among dynamic ones is not enough.
    mixed = publisher.publish({"panels": [{"preset": "campaign_pass_rate"}, CANVAS["panels"][0]]}, CTX, NOW)
    assert mixed["reused"] is False and http.dashboards


def test_cleanup_deletes_only_expired_atlas_drafts_in_the_folder(http):
    past, future = int((NOW - timedelta(hours=1)).timestamp()), int((NOW + timedelta(hours=1)).timestamp())

    def entry(uid, tags, folder=FOLDER_UID):
        http.dashboards[uid] = {"folderUid": folder, "dashboard": {"tags": tags}}
    entry("atlas-draft-old", ["atlas-draft", f"atlas-expires-{past}"])
    entry("atlas-draft-new", ["atlas-draft", f"atlas-expires-{future}"])
    entry("atlas-draft-noexp", ["atlas-draft"])
    entry("atlas-draft-badexp", ["atlas-draft", "atlas-expires-soon"])
    entry("atlas-draft-elsewhere", ["atlas-draft", f"atlas-expires-{past}"], folder="general")
    entry("maintained-board", ["atlas-draft", f"atlas-expires-{past}"])  # wrong uid prefix
    entry("atlas-draft-untagged", ["other", f"atlas-expires-{past}"])
    assert cleanup_expired(GrafanaClient(http), NOW) == 1
    assert set(http.dashboards) == {"atlas-draft-new", "atlas-draft-noexp", "atlas-draft-badexp",
                                    "atlas-draft-elsewhere", "maintained-board", "atlas-draft-untagged"}
    assert [c[1] for c in http.calls if c[0] == "delete"] == ["/api/dashboards/uid/atlas-draft-old"]


def test_cleanup_runs_on_create_and_failure_to_clean_does_not_block(publisher, http):
    http.dashboards["atlas-draft-stale"] = {"folderUid": FOLDER_UID, "dashboard": {"tags": [
        "atlas-draft", f"atlas-expires-{int((NOW - timedelta(days=1)).timestamp())}"]}}
    publisher.publish(CANVAS, CTX, NOW)
    assert "atlas-draft-stale" not in http.dashboards


def test_missing_credentials_and_http_errors_raise_a_safe_message(publisher, http, monkeypatch):
    http.fail_push = True
    with pytest.raises(GrafanaPushError, match="HTTP 500"):
        publisher.publish(CANVAS, CTX, NOW)
    monkeypatch.delenv("GRAFANA_ADMIN_PASSWORD")
    with pytest.raises(GrafanaPushError, match="Grafana not configured"):
        publisher.publish(CANVAS, CTX, NOW)


def test_link_is_the_app_grafana_base_plus_the_path_and_ignores_grafana_domain(monkeypatch):
    path = grafana_push.dashboard_path("abc", "ws 1")
    assert path == "/grafana/d/abc?var-workspace=ws%201"
    # Main server case: GRAFANA_DOMAIN is the marketing website; the app's base decides.
    monkeypatch.setenv("GRAFANA_DOMAIN", "www.virtualpytest.com")
    assert grafana_push.absolute_url(path, "https://virtualpytest.angelstreet.io/grafana/") == \
        "https://virtualpytest.angelstreet.io/grafana/d/abc?var-workspace=ws%201"
    # Pi server case: the Pi's chat sends the same app base, so the link still points at main's Grafana.
    assert grafana_push.absolute_url(path, "https://virtualpytest.angelstreet.io/grafana") .startswith("https://virtualpytest.angelstreet.io/grafana/d/abc")
    assert grafana_push.absolute_url("/grafana/d/abc", "http://lab.test:3000") == "http://lab.test:3000/d/abc"
    # No (or an unusable) base: the same-origin path, which the app's /grafana route redirects.
    for base in ("", None, "javascript:alert(1)", "https://u:p@evil.test/x", "https://x.test/a?b=1", "ftp://x.test", "https://x.test/ a", 5):
        assert grafana_push.absolute_url("/grafana/d/abc", base) == "/grafana/d/abc", base
        assert grafana_push.clean_grafana_base(base) == ""


# --------------------------------------------------------------- tool integration
def _artifact():
    panel = {"title": "P", "mark": "bar", "data": {"rows": [{"a": 1}], "row_count": 1}, "options": {},
             "provenance": {"resolved_request": dict(CANVAS["panels"][0])}}
    return {"content_type": "report-chart", "content_data": {"artifact_spec": {
        "kind": "canvas", "title": "C", "panels": [dict(panel), dict(panel, title="Q")]}}}


class FakePublisher:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def publish(self, request, context):
        self.calls.append(request)
        if self.exc:
            raise self.exc
        return self.result


def _tools(monkeypatch, publisher, artifact=None):
    tools = analytics_tools.AnalyticsTools()
    monkeypatch.setattr(tools.service, "render", lambda request, context: artifact or _artifact())
    tools.publisher = publisher
    return tools


PARAMS = {**CANVAS, "_context_team_id": TEAM}


def test_canvas_render_attaches_the_grafana_link_and_mentions_it(monkeypatch):
    link = {"path": "/grafana/d/atlas-draft-1", "uid": "atlas-draft-1", "expires_at": "2026-10-06T12:00:00+00:00", "reused": False}
    publisher = FakePublisher(link)
    result = _tools(monkeypatch, publisher).render_analytics_artifact(PARAMS)
    assert result["artifact"]["content_data"]["artifact_spec"]["grafana"] == link
    text = result["content"][0]["text"]
    assert "Grafana draft: /grafana/d/atlas-draft-1 (a path on the VirtualPyTest web app" in text  # no app base sent: the model is told not to invent a host
    assert len(publisher.calls) == 1
    # With the app's Grafana base in the chat context the answer carries an absolute link that opens.
    result = _tools(monkeypatch, FakePublisher(link)).render_analytics_artifact(
        {**PARAMS, "_context_grafana_base_url": "https://app.example.test/grafana"})
    assert "Grafana draft: https://app.example.test/grafana/d/atlas-draft-1 (expires" in result["content"][0]["text"]
    assert result["artifact"]["content_data"]["artifact_spec"]["grafana"] == link  # the canvas gets the path only


def test_push_failure_never_fails_the_render(monkeypatch):
    for exc in (GrafanaPushError("Grafana answered HTTP 500"), RuntimeError("boom with secret")):
        result = _tools(monkeypatch, FakePublisher(exc=exc)).render_analytics_artifact(PARAMS)
        assert result["isError"] is False and "grafana" not in result["artifact"]["content_data"]["artifact_spec"]
        text = result["content"][0]["text"]
        assert "Grafana draft not created:" in text and "secret" not in text


def test_single_chart_does_not_trigger_a_draft(monkeypatch):
    publisher = FakePublisher({"path": "/grafana/d/x", "uid": "x", "expires_at": None, "reused": False})
    single = {"content_type": "report-chart", "content_data": {"artifact_spec": {
        "kind": "visualization", "title": "S", "mark": "bar", "data": {"rows": [{"a": 1}], "row_count": 1}, "options": {}}}}
    _tools(monkeypatch, publisher, single).render_analytics_artifact(
        {"source_id": "script_results", "dimensions": ["device_name"], "metrics": ["run_count"], "_context_team_id": TEAM})
    _tools(monkeypatch, publisher).render_analytics_artifact({"panels": CANVAS["panels"][:1], "_context_team_id": TEAM})  # one panel is not a canvas
    assert publisher.calls == []


def test_create_grafana_draft_also_pushes(monkeypatch, tmp_path):
    tools = analytics_tools.AnalyticsTools()
    tools.drafts = GrafanaDraftService(tools.service, root=tmp_path / "tmp" / "atlas-grafana")
    publisher = FakePublisher({"path": "/grafana/d/u", "uid": "u", "expires_at": "e", "reused": False})
    tools.publisher = publisher
    result = tools.create_grafana_draft({**CANVAS["panels"][0], "_context_team_id": TEAM,
                                         "_context_grafana_base_url": "https://app.example.test/grafana"})
    assert result["isError"] is False and "Open in Grafana: https://app.example.test/grafana/d/u" in result["content"][0]["text"]
    result = tools.create_grafana_draft({**CANVAS["panels"][0], "_context_team_id": TEAM})
    assert "Open in Grafana: /grafana/d/u" in result["content"][0]["text"]
    assert publisher.calls[0]["prefer_existing"] is False
    tools.publisher = FakePublisher(exc=GrafanaPushError("Grafana not configured: missing GRAFANA_URL"))
    result = tools.create_grafana_draft({**CANVAS["panels"][0], "_context_team_id": TEAM})
    assert result["isError"] is False and "draft written to" in result["content"][0]["text"] and "not pushed" in result["content"][0]["text"]


# --------------------------------------------------------------- Pi forwarding
class RecordingRemote(RemoteAnalytics):
    def __init__(self):
        super().__init__("https://primary.example.test", "key")
        self.calls = []

    def call(self, operation, payload):
        self.calls.append((operation, payload))
        return {"path": "/grafana/d/atlas-draft-p", "uid": "atlas-draft-p", "expires_at": "e", "reused": False}


def test_a_server_without_a_datasource_forwards_the_push(http):
    remote = RecordingRemote()
    analytics = AnalyticsService(dsn="", remote=remote)
    analytics.dsn = ""
    result = GrafanaDraftPublisher(analytics, client=GrafanaClient(http)).publish(CANVAS, CTX)
    assert result["uid"] == "atlas-draft-p" and http.calls == []
    assert remote.calls[0][0] == "grafana-draft" and remote.calls[0][1]["context"]["team_id"] == TEAM


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "service-key")
    app = Flask(__name__)
    app.register_blueprint(routes.server_atlas_analytics_bp)
    monkeypatch.setattr(routes, "_team_ids_from_db", lambda user_id: {TEAM} if user_id == "user-1" else set())
    return app.test_client()


def _post(client, body, key="service-key"):
    return client.post("/server/atlas-analytics/grafana-draft", json=body, headers={"X-API-Key": key} if key else {})


def test_route_is_service_key_only_and_rechecks_the_team(client, http, monkeypatch):
    monkeypatch.setattr(GrafanaClient, "_requests", lambda self: http)
    body = {"request": CANVAS, "context": CTX.as_dict()}
    assert _post(client, body, key=None).status_code == 403
    assert _post(client, body, key="wrong").status_code == 403
    assert _post(client, {**body, "context": {**CTX.as_dict(), "team_id": "00000000-0000-0000-0000-000000000999"}}).status_code == 403
    assert _post(client, {**body, "context": {}}).status_code == 400
    assert http.dashboards == {}
    response = _post(client, body)
    assert response.status_code == 200 and response.get_json()["result"]["uid"] in http.dashboards
    assert _post(client, {**body, "context": {**CTX.as_dict(), "user_id": "auto_sign"}}).status_code == 200


def test_route_never_forwards_again_and_reports_errors_as_400(client, http, monkeypatch):
    forwarded = RecordingRemote()
    monkeypatch.delenv("SUPABASE_DB_URI", raising=False)
    monkeypatch.setattr(routes, "AnalyticsService", lambda: AnalyticsService(dsn="", remote=forwarded))
    monkeypatch.setattr(GrafanaClient, "_requests", lambda self: http)
    http.fail_push = True
    response = _post(client, {"request": CANVAS, "context": CTX.as_dict()})
    assert response.status_code == 400 and "HTTP 500" in response.get_json()["error"]
    assert forwarded.calls == []


def test_relative_link_tells_the_model_not_to_invent_a_host():
    from backend_server.src.lib.analytics.grafana_push import link_for_reply
    assert link_for_reply("/grafana/d/atlas-draft-x", "https://grafana.example.com") == "https://grafana.example.com/d/atlas-draft-x"
    text = link_for_reply("/grafana/d/atlas-draft-x", "")
    assert text.startswith("/grafana/d/atlas-draft-x ") and "never add or guess a host" in text
