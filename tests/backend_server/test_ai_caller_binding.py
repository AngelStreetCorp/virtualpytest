"""TASK-87: every /server/* request binds the AI caller (ui / api / forwarded by a host)."""
import os
import sys

import pytest
from flask import Flask, jsonify, request

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
for path in (_repo_root, os.path.join(_repo_root, "backend_server"), os.path.join(_repo_root, "backend_server", "src")):
    sys.path.insert(0, path)

from backend_server.src.lib.ai_caller_binding import install_ai_caller_binding  # noqa: E402
from shared.src.lib.ai import caller  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(caller, "_env_loaded", True)
    app = Flask("t")

    @app.before_request
    def fake_auth():  # stands in for the auth guard, which runs first
        role = request.headers.get("X-Test-Role")
        if role:
            request.user_role = role
            request.user_id = request.headers.get("X-Test-User")

    install_ai_caller_binding(app)

    @app.route("/server/who")
    def who():
        return jsonify(caller.current())

    @app.route("/elsewhere")
    def elsewhere():
        return jsonify(caller.current())

    return app.test_client()


def test_a_signed_in_user_is_origin_ui_with_route(client):
    body = client.get("/server/who", headers={"X-Test-Role": "admin", "X-Test-User": "u-1"}).get_json()
    assert body == {"origin": "ui", "user_id": "u-1", "route": "/server/who"}


def test_the_service_key_is_origin_api_unless_a_host_forwards_who_asked(client):
    assert client.get("/server/who", headers={"X-Test-Role": "service"}).get_json() == {"origin": "api"}
    header = {"X-Test-Role": "service", "X-VPT-Caller": '{"origin":"script","script_result_id":"r1","host_name":"h"}'}
    assert client.get("/server/who", headers=header).get_json() == {
        "origin": "script", "script_result_id": "r1", "host_name": "h"}


def test_a_user_cannot_spoof_the_header_and_context_is_cleared_after(client):
    spoof = {"X-Test-Role": "viewer", "X-Test-User": "u-2", "X-VPT-Caller": '{"origin":"script","user_id":"other"}'}
    assert client.get("/server/who", headers=spoof).get_json()["user_id"] == "u-2"
    assert caller.current() == {}
    assert client.get("/elsewhere").get_json() == {}  # not a /server/ path: nothing bound


def test_a_host_call_with_no_entry_point_origin_is_monitoring_not_api(client):
    """BUG-0496: the localize second opinion / triage run in a host process: header has host_name only."""
    header = {"X-Test-Role": "service", "X-VPT-Caller": '{"host_name":"vpt-pi1"}'}
    assert client.get("/server/who", headers=header).get_json() == {"origin": "monitoring", "host_name": "vpt-pi1"}
    # an explicit origin from the host is kept, and a bare service call stays api
    header = {"X-Test-Role": "service", "X-VPT-Caller": '{"host_name":"h","origin":"background","job":"x"}'}
    assert client.get("/server/who", headers=header).get_json()["origin"] == "background"
    assert client.get("/server/who", headers={"X-Test-Role": "service"}).get_json() == {"origin": "api"}
