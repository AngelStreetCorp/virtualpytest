"""TASK-179 P1: platform server list: validation, 60 s cache, self name, GET/PUT routes (no DB, no network)."""
import os
import sys

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.lib.servers import registry  # noqa: E402
from backend_server.src.routes import server_servers_routes as routes  # noqa: E402
from shared.src.lib.database import platform_servers_db as db  # noqa: E402
from tests.backend_server._task42_common import make_task42_app  # noqa: E402

pytestmark = pytest.mark.unit

ROWS = [
    {"name": "Awesomation", "url": "https://virtualpytest.angelstreet.io", "enabled": True, "sort_order": 0},
    {"name": "vpt-pi1", "url": "https://vpt-pi1.angelstreet.io", "enabled": True, "sort_order": 10},
    {"name": "old", "url": "https://old.example.com", "enabled": False, "sort_order": 20},
]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("SERVER_NAME", raising=False)
    registry.invalidate()
    yield
    registry.invalidate()


@pytest.fixture
def calls(monkeypatch):
    n = {"list": 0}

    def fake_list(include_disabled=False):
        n["list"] += 1
        return [dict(r) for r in ROWS if include_disabled or r["enabled"]]

    monkeypatch.setattr(db, "list_servers", fake_list)
    return n


# --- validation -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://a.example.com", "https://a.example.com:8443", "http://localhost:5109",
                                 "http://192.168.0.103:5109", "http://10.1.2.3", "http://vpt.local"])
def test_url_ok(url):
    assert db.validate_url(url) == url


@pytest.mark.parametrize("url", ["", None, "a.example.com", "ftp://a.example.com", "https://a.example.com/",
                                 "https://a.example.com/server", "https://a.example.com?x=1", "http://a.example.com",
                                 "http://8.8.8.8"])
def test_url_bad(url):
    with pytest.raises(db.InvalidServers):
        db.validate_url(url)


@pytest.mark.parametrize("name", ["Awesomation", "vpt-pi1", "QualiAI", "a_b", "9x"])
def test_name_ok(name):
    assert db.validate_rows([{"name": name, "url": "https://a.example.com"}])[0]["name"] == name


@pytest.mark.parametrize("name", ["", "-x", "_x", "a b", "a/b", None, 5])
def test_name_bad(name):
    with pytest.raises(db.InvalidServers):
        db.validate_rows([{"name": name, "url": "https://a.example.com"}])


def test_duplicate_names_case_insensitive():
    with pytest.raises(db.InvalidServers, match="duplicate"):
        db.validate_rows([{"name": "QualiAI", "url": "https://a.example.com"},
                          {"name": "qualiai", "url": "https://b.example.com"}])


# --- cache + self name ------------------------------------------------------------------------------------------------

def test_cache_hits_db_once_until_invalidate(calls):
    registry.servers()
    registry.servers()
    registry.others()
    assert calls["list"] == 1
    registry.invalidate()
    registry.servers()
    assert calls["list"] == 2


def test_cache_expires_after_ttl(calls, monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(registry.time, "monotonic", lambda: t["now"])
    registry.servers()
    t["now"] += registry.CACHE_TTL_SECONDS + 1
    registry.servers()
    assert calls["list"] == 2


@pytest.mark.parametrize("value", [None, "", "server", "default", "Default"])
def test_self_name_defaults_to_none(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("SERVER_NAME", value)
    assert registry.self_name() is None


def test_self_matches_case_insensitive_and_others_skip_it(calls, monkeypatch):
    monkeypatch.setenv("SERVER_NAME", "awesomation")
    assert registry.self_in_list()
    assert [r["name"] for r in registry.others()] == ["vpt-pi1"]  # self skipped, disabled skipped


# --- routes -----------------------------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, calls):
    admin = {"v": False}
    monkeypatch.setattr("backend_server.src.lib.auth_middleware._caller_is_platform_admin", lambda: admin["v"])
    app, _, _ = make_task42_app(monkeypatch, blueprints=[routes.server_servers_bp], role="admin")
    c = app.test_client()
    c.admin = admin
    return c


def test_get_shape_and_warning_for_unset_server_name(client):
    body = client.get("/server/servers").get_json()
    assert [s["name"] for s in body["servers"]] == ["Awesomation", "vpt-pi1", "old"]
    assert set(body["servers"][0]) == {"name", "url", "enabled", "sort_order"}
    assert body["self_name"] is None and body["self_in_list"] is False
    assert "SERVER_NAME" in body["warning"]


def test_get_warns_when_self_not_in_list_and_no_warning_when_ok(client, monkeypatch):
    monkeypatch.setenv("SERVER_NAME", "ghost")
    assert "ghost" in client.get("/server/servers").get_json()["warning"]
    monkeypatch.setenv("SERVER_NAME", "vpt-pi1")
    body = client.get("/server/servers").get_json()
    assert body["self_in_list"] is True and body["warning"] is None


def test_get_missing_table_is_200_empty_with_warning(client, monkeypatch):
    def boom(include_disabled=False):
        raise db.TableMissing("nope")
    monkeypatch.setattr(db, "list_servers", boom)
    resp = client.get("/server/servers")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["servers"] == [] and "table missing" in body["warning"]


def test_put_requires_platform_admin(client, monkeypatch):
    monkeypatch.setattr(db, "replace_servers", lambda rows: pytest.fail("must not write"))
    resp = client.put("/server/servers", json={"servers": ROWS})
    assert resp.status_code == 403


def test_put_replaces_and_invalidates_cache(client, monkeypatch, calls):
    client.admin["v"] = True
    seen = {}
    monkeypatch.setattr(db, "replace_servers", lambda rows: seen.setdefault("rows", db.validate_rows(rows)))
    client.get("/server/servers")
    before = calls["list"]
    resp = client.put("/server/servers", json={"servers": [{"name": "n1", "url": "https://n1.example.com"}]})
    assert resp.status_code == 200
    assert seen["rows"][0]["name"] == "n1"
    assert calls["list"] == before + 1  # cache was invalidated, the response re-read the list


@pytest.mark.parametrize("servers", [
    [{"name": "bad name", "url": "https://a.example.com"}],
    [{"name": "a", "url": "https://a.example.com/path"}],
    [{"name": "a", "url": "http://8.8.8.8"}],
    [{"name": "a", "url": "https://a.example.com"}, {"name": "A", "url": "https://b.example.com"}],
    "nope",
])
def test_put_400_on_bad_rows(client, monkeypatch, servers):
    client.admin["v"] = True
    monkeypatch.setattr(db, "_client", lambda: pytest.fail("must not reach the database"))
    resp = client.put("/server/servers", json={"servers": servers})
    assert resp.status_code == 400
    assert resp.get_json()["error"]


def test_put_400_without_body(client):
    client.admin["v"] = True
    assert client.put("/server/servers", json={"x": 1}).status_code == 400
