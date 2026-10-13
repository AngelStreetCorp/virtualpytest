"""AI gateway routes accept only the service X-API-Key (TASK-30).

Run: pytest tests/backend_server/test_ai_gateway_auth.py -v
"""
import os
import sys

import pytest
from flask import Flask

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
for path in (_repo_root, os.path.join(_repo_root, "backend_server"), os.path.join(_repo_root, "backend_server", "src")):
    sys.path.insert(0, path)

from backend_server.src.routes import server_ai_routing_routes as routes  # noqa: E402

pytestmark = pytest.mark.unit

GATEWAY = [
    ("/server/ai/complete", {"usage": "vision.ask", "prompt": "x"}),
    ("/server/ai/decide", {"usage": "text.decision", "state": "s", "questions": {}}),
    ("/server/ai/resolve", {"usage": "vision.ask"}),
    ("/server/ai/stats", {"usage": "vision.ask"}),
    ("/server/ai/openai/agent.browser/chat/completions", {"messages": []}),
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "service-secret")
    # Past the guard, fail fast instead of touching a DB.
    monkeypatch.setattr(routes.router, "resolve",
                        lambda *a, **k: (_ for _ in ()).throw(routes.router.AIRoutingError("no route (test)")))
    monkeypatch.setattr(routes.call_log, "submit", lambda *a, **k: None)
    app = Flask("t")
    app.register_blueprint(routes.server_ai_routing_bp)
    return app.test_client()


@pytest.mark.parametrize("url,body", GATEWAY)
def test_refused_without_service_key(client, url, body):
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers={"X-API-Key": "wrong"}).status_code == 403


@pytest.mark.parametrize("url,body", GATEWAY)
def test_allowed_with_service_key(client, url, body):
    response = client.post(url, json=body, headers={"X-API-Key": "service-secret"})
    assert response.status_code != 403


def test_decide_runs_the_decision_on_the_server(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(routes.router, "resolve_profile", lambda profile, usage, team: ("pinned", profile, usage, team))

    def fake_decide(resolution, state, questions, timeout_s=None, refs=None, log=True):
        seen.update(resolution=resolution, state=state, refs=refs, log=log, timeout_s=timeout_s)
        return {"success": True, "answers": {"q": {"type": "noul", "noul": 0.9}}, "decision_id": "d1"}
    monkeypatch.setattr(routes.decisions, "decide", fake_decide)
    body = {"usage": "text.decision", "profile": "jev", "team_id": "t1", "state": "s",
            "questions": {"q": {"type": "noul"}}, "refs": {"a": 1}, "log": False, "timeout_s": 20}
    data = client.post("/server/ai/decide", json=body, headers={"X-API-Key": "service-secret"}).get_json()
    assert data["success"] and data["decision_id"] == "d1"
    assert seen == {"resolution": ("pinned", "jev", "text.decision", "t1"), "state": "s", "refs": {"a": 1},
                    "log": False, "timeout_s": 20}


def test_decide_without_a_route_is_a_failed_result(client):
    data = client.post("/server/ai/decide", json={"usage": "text.decision", "state": "s", "questions": {}},
                       headers={"X-API-Key": "service-secret"}).get_json()
    assert data["success"] is False and "no route" in data["error"] and data["decision_id"] is None


def test_refused_when_server_has_no_api_key(client, monkeypatch):
    monkeypatch.delenv("API_KEY")
    assert client.post("/server/ai/complete", json={}, headers={"X-API-Key": ""}).status_code == 403
