"""TASK-179 P3: scope=all fan-out helper, decorator and merges (no DB, no network: the HTTP call is faked)."""
import os
import sys
import time

import gevent
import pytest
import requests
from flask import Flask, jsonify

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.servers import fanout, merges, registry  # noqa: E402
from backend_server.src.lib.servers.scope import supports_all_servers  # noqa: E402
from shared.src.lib.database import platform_servers_db as db  # noqa: E402

pytestmark = pytest.mark.unit

ROWS = [
    {"name": "Awesomation", "url": "https://main.example.com", "enabled": True, "sort_order": 0},
    {"name": "vpt-pi1", "url": "https://pi1.example.com", "enabled": True, "sort_order": 10},
    {"name": "vpt-pi4", "url": "https://pi4.example.com", "enabled": True, "sort_order": 20},
    {"name": "old", "url": "https://old.example.com", "enabled": False, "sort_order": 30},
]


class FakeResp:
    def __init__(self, status=200, body=None, bad_json=False):
        self.status_code, self._body, self._bad = status, body, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._body


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("SERVER_NAME", "Awesomation")
    monkeypatch.setattr(db, "list_servers", lambda include_disabled=False: [dict(r) for r in ROWS if include_disabled or r["enabled"]])
    registry.invalidate()
    yield
    registry.invalidate()


@pytest.fixture
def peers(monkeypatch):
    """Fake the HTTP call: ``peers.replies[host] = FakeResp | exception | callable``; records every call."""
    state = type("S", (), {})()
    state.replies, state.calls = {}, []

    def fake_get(url, params, headers, timeout):
        state.calls.append({"url": url, "params": dict(params), "headers": dict(headers)})
        reply = state.replies.get(url.split("/")[2], FakeResp(200, {"hosts": []}))
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(fanout, "_get", fake_get)
    return state


def _host(name, url, devices=1):
    return {"host_name": name, "host_url": url, "device_count": devices,
            "devices": [{"device_id": f"device{i}", "video_stream_path": "/host/stream/capture1"} for i in range(devices)]}


@pytest.fixture
def app(peers):
    app = Flask(__name__)
    seen = {"views": 0}

    @app.route("/server/system/getAllHosts")
    @supports_all_servers(merges.merge_hosts)
    def hosts():
        seen["views"] += 1
        return jsonify({"success": True, "server_info": {"server_name": "Awesomation"},
                        "hosts": [_host("h1", "/host/h1", 2)]})

    @app.route("/server/control/lockedDevices")
    @supports_all_servers(merges.merge_locked_devices)
    def locks():
        return jsonify({"success": True, "locked_devices": {"h1:device1": {"host_name": "h1", "owner_user_id": "u1"}}}), 200

    @app.route("/server/boom")
    @supports_all_servers(merges.merge_hosts)
    def boom():
        return jsonify({"success": False, "error": "nope"}), 500

    app.seen = seen
    return app


BEARER = {"Authorization": "Bearer user-jwt"}


# --- helper -----------------------------------------------------------------------------------------------------------

def test_all_servers_skips_self_and_disabled_and_sends_scope_local(app, peers):
    with app.test_request_context("/x?include_system_stats=true&scope=all", headers=BEARER):
        results = fanout.all_servers("/server/system/getAllHosts", {"include_system_stats": "true", "scope": "all"})
    assert [r.server for r in results] == ["vpt-pi1", "vpt-pi4"]
    assert [c["url"] for c in peers.calls] == ["https://pi1.example.com/server/system/getAllHosts",
                                               "https://pi4.example.com/server/system/getAllHosts"]
    assert all(c["params"] == {"include_system_stats": "true", "scope": "local"} for c in peers.calls)


def test_only_authorization_and_auto_sign_are_forwarded(app, peers):
    headers = {**BEARER, "X-Auto-Sign": "tok", "X-API-Key": "service-key", "Cookie": "a=b"}
    with app.test_request_context("/x", headers=headers):
        fanout.all_servers("/p")
    sent = peers.calls[0]["headers"]
    assert sent["Authorization"] == "Bearer user-jwt" and sent["X-Auto-Sign"] == "tok"
    assert "X-API-Key" not in sent and "Cookie" not in sent
    assert "VirtualPyTest-server" in sent["User-Agent"] and "python-requests" not in sent["User-Agent"]


def test_service_key_only_is_refused(app, peers):
    with app.test_request_context("/x", headers={"X-API-Key": "service-key"}):
        with pytest.raises(fanout.NeedsSignedInUser):
            fanout.all_servers("/p")
    assert peers.calls == []


def test_failures_become_rows_not_exceptions(app, peers):
    peers.replies["pi1.example.com"] = FakeResp(401, {"error": "x"})
    peers.replies["pi4.example.com"] = requests.ConnectionError("down")
    with app.test_request_context("/x", headers=BEARER):
        r1, r4 = fanout.all_servers("/p")
    assert (r1.ok, r1.status, r1.error) == (False, 401, "401")
    assert (r4.ok, r4.error) == (False, "unreachable")


def test_bad_json_and_requests_timeout(app, peers):
    peers.replies["pi1.example.com"] = FakeResp(200, bad_json=True)
    peers.replies["pi4.example.com"] = requests.ReadTimeout("slow")
    with app.test_request_context("/x", headers=BEARER):
        r1, r4 = fanout.all_servers("/p")
    assert (r1.ok, r1.error) == (False, "bad response")
    assert (r4.ok, r4.error) == (False, "timeout")


def test_slow_peer_times_out_within_budget_and_others_still_answer(app, peers):
    def slow():
        gevent.sleep(5)
        return FakeResp(200, {"hosts": []})

    peers.replies["pi4.example.com"] = slow
    peers.replies["pi1.example.com"] = FakeResp(200, {"hosts": [_host("p", "/host/p")]})
    started = time.monotonic()
    with app.test_request_context("/x", headers=BEARER):
        r1, r4 = fanout.all_servers("/p", timeout=0.3)
    assert time.monotonic() - started < 1.5
    assert r1.ok and (r4.ok, r4.error) == (False, "timeout")


# --- decorator --------------------------------------------------------------------------------------------------------

def test_scope_absent_or_local_runs_the_view_unchanged(app, peers):
    c = app.test_client()
    for qs in ("", "?scope=local"):
        body = c.get("/server/system/getAllHosts" + qs, headers=BEARER).get_json()
        assert "servers" not in body and body["hosts"][0]["host_url"] == "/host/h1"
    assert peers.calls == []


def test_scope_all_merges_local_and_peers_with_summary(app, peers):
    peers.replies["pi1.example.com"] = FakeResp(200, {"hosts": [_host("p1", "/host/p1", 3)]})
    peers.replies["pi4.example.com"] = FakeResp(401, {"error": "no"})
    body = app.test_client().get("/server/system/getAllHosts?scope=all", headers=BEARER).get_json()
    assert body["server_info"] == {"server_name": "Awesomation"}  # other local fields kept
    assert [(h["host_name"], h["server"], h["host_url"]) for h in body["hosts"]] == [
        ("h1", "Awesomation", "https://main.example.com/host/h1"),
        ("p1", "vpt-pi1", "https://pi1.example.com/host/p1")]
    s = {x["name"]: x for x in body["servers"]}
    assert list(s) == ["Awesomation", "vpt-pi1", "vpt-pi4"]
    assert (s["Awesomation"]["ok"], s["Awesomation"]["host_count"], s["Awesomation"]["device_count"]) == (True, 1, 2)
    assert (s["vpt-pi1"]["host_count"], s["vpt-pi1"]["device_count"]) == (1, 3)
    assert (s["vpt-pi4"]["ok"], s["vpt-pi4"]["status"], s["vpt-pi4"]["error"]) == (False, 401, "401")
    assert set(s["vpt-pi4"]) == {"name", "url", "ok", "status", "error", "latency_ms", "host_count", "device_count"}
    assert "warning" not in body
    assert all(c["params"]["scope"] == "local" for c in peers.calls)


def test_device_path_fields_are_left_alone(app, peers):
    body = app.test_client().get("/server/system/getAllHosts?scope=all", headers=BEARER).get_json()
    assert body["hosts"][0]["devices"][0]["video_stream_path"] == "/host/stream/capture1"


def test_absolute_host_url_unchanged_and_report_urls_prefixed():
    host = _host("h", "https://other.example.com/host/h")
    host["devices"][0]["device_info_report"] = {"report_url": "/r/1", "scanned_at": "t", "video_url": "https://r2/x"}
    out = merges.merge_hosts({"hosts": [host]}, {"name": "A", "url": "https://a.example.com"}, [])
    h = out["hosts"][0]
    assert h["host_url"] == "https://other.example.com/host/h"
    assert h["devices"][0]["device_info_report"] == {"report_url": "https://a.example.com/r/1", "scanned_at": "t",
                                                     "video_url": "https://r2/x"}


def test_service_key_only_scope_all_is_403_and_nothing_is_called(app, peers):
    r = app.test_client().get("/server/system/getAllHosts?scope=all", headers={"X-API-Key": "service-key"})
    assert r.status_code == 403 and "signed-in user" in r.get_json()["error"]
    assert peers.calls == [] and app.seen["views"] == 0


def test_auto_sign_is_enough(app, peers):
    r = app.test_client().get("/server/system/getAllHosts?scope=all", headers={"X-Auto-Sign": "tok"})
    assert r.status_code == 200 and peers.calls[0]["headers"]["X-Auto-Sign"] == "tok"


def test_failing_local_view_is_returned_as_is(app, peers):
    r = app.test_client().get("/server/boom?scope=all", headers=BEARER)
    assert r.status_code == 500 and peers.calls == []


def test_self_not_in_list_still_answers_with_warning(app, peers, monkeypatch):
    monkeypatch.setenv("SERVER_NAME", "ghost")
    registry.invalidate()
    body = app.test_client().get("/server/system/getAllHosts?scope=all", headers=BEARER).get_json()
    assert "not in the server list" in body["warning"]
    assert body["servers"][0]["name"] == "ghost"
    assert [s["name"] for s in body["servers"]][1:] == ["Awesomation", "vpt-pi1", "vpt-pi4"]  # ghost not skipped: all peers
    assert body["hosts"][0]["server"] == "ghost"


def test_locked_devices_merge(app, peers):
    peers.replies["pi1.example.com"] = FakeResp(200, {"locked_devices": {"h1:device1": {"host_name": "h1"}}})
    peers.replies["pi4.example.com"] = requests.ConnectionError("down")
    body = app.test_client().get("/server/control/lockedDevices?scope=all", headers=BEARER).get_json()
    assert sorted(body["locked_devices"]) == ["Awesomation:h1:device1", "vpt-pi1:h1:device1"]
    assert body["locked_devices"]["vpt-pi1:h1:device1"]["server"] == "vpt-pi1"
    s = {x["name"]: x for x in body["servers"]}
    assert (s["Awesomation"]["lock_count"], s["vpt-pi1"]["lock_count"]) == (1, 1)
    assert (s["vpt-pi4"]["ok"], s["vpt-pi4"]["error"], s["vpt-pi4"]["lock_count"]) == (False, "unreachable", 0)


def test_peer_payload_without_the_field_is_a_bad_response(app, peers):
    peers.replies["pi1.example.com"] = FakeResp(200, {"success": True})
    body = app.test_client().get("/server/system/getAllHosts?scope=all", headers=BEARER).get_json()
    s = {x["name"]: x for x in body["servers"]}
    assert (s["vpt-pi1"]["ok"], s["vpt-pi1"]["error"]) == (False, "bad response")
