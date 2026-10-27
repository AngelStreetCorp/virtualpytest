"""TASK-179 P4: Atlas on all servers - the per-turn login, the ContextVar, owner lookup and the section 6 places.

No DB, no network, no devices: HTTP and the host registry are faked."""
import asyncio
import logging
import os
import sys
from types import SimpleNamespace

import gevent
import pytest
from flask import Flask

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend_server", "src"))   # the app imports `agent` this way

try:
    from backend_server.src.lib.servers import fanout, owner, registry, turn  # noqa: E402
    from backend_server.src.lib.utils import server_utils  # noqa: E402
    from backend_server.src.mcp import mcp_server  # noqa: E402
    from backend_server.src.mcp.tools import device_tools, navigation_tools, screenshot_tools  # noqa: E402
    from backend_server.src.mcp.tool_definitions.build_definitions import get_builder  # noqa: E402
    from backend_server.src.mcp.utils import api_client as api_client_module  # noqa: E402
    from backend_server.src.routes import server_agent_routes, server_stream_proxy_routes  # noqa: E402
    from shared.src.lib.database import platform_servers_db as db  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"MCP runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

SECRET = "eyJ-secret-user-token-123"
ROWS = [
    {"name": "Awesomation", "url": "https://main.example.com", "enabled": True, "sort_order": 0},
    {"name": "vpt-pi1", "url": "https://pi1.example.com", "enabled": True, "sort_order": 10},
    {"name": "vpt-pi4", "url": "https://pi4.example.com", "enabled": True, "sort_order": 20},
]


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("SERVER_NAME", "Awesomation")
    monkeypatch.setenv("API_KEY", "service-key-xyz")
    monkeypatch.setattr(db, "list_servers", lambda include_disabled=False: [dict(r) for r in ROWS])
    registry.invalidate()
    owner.invalidate()
    yield
    registry.invalidate()
    owner.invalidate()


def _result(server, ok=True, hosts=(), error=None):
    return fanout.ServerResult(server=server, url=f"https://{server}.example.com", ok=ok, status=200 if ok else 401,
                               data={"hosts": [{"host_name": h} for h in hosts]} if ok else None, error=error)


@pytest.fixture
def platform(monkeypatch):
    """Hosts per server: this server's registry and the other servers' answers."""
    state = SimpleNamespace(local=["local-1"], peers={"vpt-pi1": ["pi1-box"], "vpt-pi4": ["pi4-box"]}, calls=0)

    def fake_all_servers(path, params=None, *, timeout=4, headers=None):
        state.calls += 1
        assert "X-API-Key" not in (headers or {})
        out = []
        for name, hosts in state.peers.items():
            out.append(hosts if isinstance(hosts, fanout.ServerResult) else _result(name, hosts=hosts))
        return out

    monkeypatch.setattr(owner, "all_servers", fake_all_servers)
    monkeypatch.setattr(owner, "_local_host_names", lambda: list(state.local))
    return state


# ---- the turn ContextVar -----------------------------------------------------------------------------------------

def test_turn_is_per_greenlet_and_never_leaks():
    seen = {}

    def chat(name, token, pause):
        t = turn.bind_turn(token=token, scope="all")
        gevent.sleep(pause)   # the other chat binds and reads while this one waits
        seen[name] = turn.current().headers["Authorization"]
        turn.reset_turn(t)
        seen[name + "_after"] = turn.current()

    jobs = [gevent.spawn(chat, "a", "tok-a", 0.05), gevent.spawn(chat, "b", "tok-b", 0.01)]
    gevent.joinall(jobs, raise_error=True)
    assert seen["a"] == "Bearer tok-a" and seen["b"] == "Bearer tok-b"
    assert seen["a_after"] is None and seen["b_after"] is None
    assert turn.current() is None   # the main greenlet never saw either


def test_turn_bound_inside_a_coroutine_reaches_sync_tool_code_and_is_reset():
    async def turn_body():
        t = turn.bind_turn(token="tok-c")
        try:
            await asyncio.sleep(0)
            return turn.current().headers["Authorization"]   # a tool runs synchronously inside the coroutine
        finally:
            turn.reset_turn(t)

    assert asyncio.run(turn_body()) == "Bearer tok-c"
    assert turn.current() is None


def test_turn_without_credential_is_no_turn():
    t = turn.bind_turn(token="", auto_sign=None, scope="all")
    try:
        assert turn.current() is None
    finally:
        turn.reset_turn(t)


def test_malformed_credentials_are_dropped_and_never_printed():
    assert turn.credential_headers(token="abc\r\nX-Evil: 1") == {}
    assert turn.credential_headers(token="x" * 5000) == {}
    assert turn.credential_headers(token=SECRET, auto_sign="sig") == {"Authorization": f"Bearer {SECRET}",
                                                                      "X-Auto-Sign": "sig"}
    t = turn.bind_turn(token=SECRET, scope="all")
    try:
        assert SECRET not in repr(turn.current()) and SECRET not in str(turn.current())
    finally:
        turn.reset_turn(t)


def test_use_target_needs_a_signed_in_turn():
    with pytest.raises(RuntimeError):
        with turn.use_target("vpt-pi4", "https://pi4.example.com"):
            pass


# ---- MCPAPIClient ------------------------------------------------------------------------------------------------

class _Resp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"success": True}


@pytest.fixture
def http(monkeypatch):
    calls = []

    def make(verb):
        def fake(url, **kwargs):
            calls.append({"verb": verb, "url": url, "headers": dict(kwargs.get("headers") or {})})
            return _Resp()
        return fake

    for verb in ("get", "post", "put", "delete"):
        monkeypatch.setattr(api_client_module.requests, verb, make(verb))
    return calls


def _call_all_verbs(client):
    client.get("/x")
    client.post("/x", data={})
    client.put("/x", data={})
    client.delete("/x")


def test_client_keeps_service_key_and_local_url_outside_a_turn(http):
    _call_all_verbs(api_client_module.MCPAPIClient())
    assert len(http) == 4
    assert all(c["url"].startswith("http://localhost:5109") for c in http)
    assert all(c["headers"].get("X-API-Key") == "service-key-xyz" and "Authorization" not in c["headers"] for c in http)


def test_client_sends_the_user_not_the_service_key_in_a_turn_and_follows_the_target(http):
    client = api_client_module.MCPAPIClient()
    t = turn.bind_turn(token=SECRET, scope="all")
    try:
        _call_all_verbs(client)
        with turn.use_target("vpt-pi4", "https://pi4.example.com/"):
            _call_all_verbs(client)
        _call_all_verbs(client)   # the target is gone again
    finally:
        turn.reset_turn(t)
    assert [c["url"].split("/x")[0] for c in http] == (["http://localhost:5109"] * 4 + ["https://pi4.example.com"] * 4
                                                        + ["http://localhost:5109"] * 4)
    for c in http:
        assert c["headers"]["Authorization"] == f"Bearer {SECRET}"
        assert "X-API-Key" not in c["headers"]


def test_two_chats_do_not_share_the_client_credential(http):
    client = api_client_module.MCPAPIClient()

    def chat(token, pause):
        t = turn.bind_turn(token=token)
        gevent.sleep(pause)
        client.get("/y")
        turn.reset_turn(t)

    gevent.joinall([gevent.spawn(chat, "one", 0.04), gevent.spawn(chat, "two", 0.01)], raise_error=True)
    assert sorted(c["headers"]["Authorization"] for c in http) == ["Bearer one", "Bearer two"]


# ---- owner lookup ------------------------------------------------------------------------------------------------

def _in_turn(**kwargs):
    return turn.bind_turn(token=SECRET, **kwargs)


def test_owner_found_on_one_server(platform):
    t = _in_turn(scope="all")
    try:
        row = owner.resolve("PI4-BOX")   # case-insensitive
        assert row["name"] == "vpt-pi4" and row["url"] == "https://pi4.example.com"
        assert owner.resolve("local-1") is None   # this server owns it: no target
    finally:
        turn.reset_turn(t)


def test_owner_none_says_not_found_and_names_servers_that_could_not_be_asked(platform):
    platform.peers["vpt-pi4"] = _result("vpt-pi4", ok=False, error="401")
    t = _in_turn(scope="all")
    try:
        with pytest.raises(owner.OwnerError) as err:
            owner.resolve("ghost")
        assert "not found on any server" in str(err.value) and "vpt-pi4: 401" in str(err.value)
    finally:
        turn.reset_turn(t)


def test_two_servers_with_the_same_host_name_ask_which_never_pick(platform):
    platform.peers["vpt-pi1"] = ["shared", "pi1-box"]
    platform.peers["vpt-pi4"] = ["shared"]
    t = _in_turn(scope="all")
    try:
        with pytest.raises(owner.OwnerError) as err:
            owner.resolve("shared")
        assert "vpt-pi1" in str(err.value) and "vpt-pi4" in str(err.value) and "server=" in str(err.value)
        assert owner.resolve("shared", explicit_server="vpt-pi4")["name"] == "vpt-pi4"   # the answer settles it
    finally:
        turn.reset_turn(t)


def test_owner_order_explicit_then_scope_then_selected_host_then_list(platform):
    t = _in_turn(scope="all", selected_host="pi1-box", selected_host_server="vpt-pi1")
    try:
        platform.calls = 0
        assert owner.resolve("pi1-box")["name"] == "vpt-pi1"
        assert platform.calls == 0                      # the page told us: no fan-out
        assert owner.resolve("pi1-box", "vpt-pi4")["name"] == "vpt-pi4"   # explicit wins
        with pytest.raises(owner.OwnerError):
            owner.resolve("pi1-box", "no-such-server")
    finally:
        turn.reset_turn(t)
    t = _in_turn(scope="vpt-pi4")                       # one server picked: everything is on it
    try:
        assert owner.resolve("whatever")["name"] == "vpt-pi4"
        assert owner.resolve("")["name"] == "vpt-pi4"   # even a call with no host
    finally:
        turn.reset_turn(t)
    t = _in_turn(scope="Awesomation")                   # this server picked: stay local
    try:
        assert owner.resolve("local-1") is None
    finally:
        turn.reset_turn(t)


def test_unknown_picker_scope_is_ignored_not_an_error(platform):
    t = _in_turn(scope="a label the list does not know", selected_host_server="also unknown")
    try:
        assert owner.resolve("pi4-box")["name"] == "vpt-pi4"
    finally:
        turn.reset_turn(t)


def test_host_list_is_cached_30_seconds_per_user(platform):
    t = _in_turn(scope="all")
    try:
        owner.resolve("pi4-box")
        owner.resolve("pi1-box")
        assert platform.calls == 1
    finally:
        turn.reset_turn(t)
    t = turn.bind_turn(token="another-user", scope="all")
    try:
        owner.resolve("pi4-box")
        assert platform.calls == 2
    finally:
        turn.reset_turn(t)


def test_no_turn_means_no_routing(platform):
    assert owner.resolve("pi4-box") is None
    with owner.route_for_call("pi4-box"):
        assert turn.target_url() is None


# ---- handle_tool_call routes the call and keeps `server` out of the tool ----------------------------------------

def _server_with(handler):
    srv = object.__new__(mcp_server.VirtualPyTestMCPServer)
    srv.logger = logging.getLogger("test-mcp")
    srv.formatter = mcp_server.MCPFormatter()
    srv.validator = mcp_server.InputValidator()
    srv._tool_schemas = {}
    srv.tool_handlers = {"probe": handler}
    return srv


def test_handle_tool_call_points_the_client_at_the_owner_for_that_call_only(platform):
    seen = []

    def handler(params):
        seen.append((dict(params), turn.target_url()))
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    srv = _server_with(handler)
    t = _in_turn(scope="all")
    try:
        srv.handle_tool_call("probe", {"host_name": "pi4-box", "server": ""})
        srv.handle_tool_call("probe", {"host_name": "local-1"})
        srv.handle_tool_call("probe", {})
        assert turn.target_url() is None
    finally:
        turn.reset_turn(t)
    assert seen[0] == ({"host_name": "pi4-box"}, "https://pi4.example.com")   # `server` is routing, not an argument
    assert seen[1][1] is None and seen[2][1] is None


def test_handle_tool_call_without_a_turn_is_unchanged(platform):
    seen = []
    srv = _server_with(lambda p: seen.append((dict(p), turn.target_url())) or {"content": [], "isError": False})
    srv.handle_tool_call("probe", {"host_name": "pi4-box"})
    assert seen == [({"host_name": "pi4-box"}, None)] and platform.calls == 0


def test_handle_tool_call_reports_an_ambiguous_host_as_an_error(platform):
    platform.peers["vpt-pi1"] = ["dup"]
    platform.peers["vpt-pi4"] = ["dup"]
    srv = _server_with(lambda p: {"content": [], "isError": False})
    t = _in_turn(scope="all")
    try:
        with pytest.raises(ValueError) as err:
            srv.handle_tool_call("probe", {"host_name": "dup"})
        assert "exists on 2 servers" in str(err.value)
    finally:
        turn.reset_turn(t)


def test_tools_with_host_name_take_an_optional_server_argument():
    schema = get_builder().get_tool("execute_device_action")["inputSchema"]["properties"]
    assert "host_name" in schema and schema["server"]["type"] == "string"
    no_host = [d for d in get_builder().get_all_tools() if "host_name" not in d["inputSchema"].get("properties", {})]
    assert no_host and all("server" not in d["inputSchema"].get("properties", {}) for d in no_host)


# ---- reads: list_hosts / get_device_info -------------------------------------------------------------------------

MERGED = {
    "success": True,
    "hosts": [
        {"host_name": "local-1", "server": "Awesomation", "status": "online", "devices": [{"device_id": "device1"}],
         "host_api_url": "http://10.0.0.1:6109"},
        {"host_name": "pi4-box", "server": "vpt-pi4", "status": "online", "devices": [{"device_id": "device1"},
                                                                                       {"device_id": "device2"}],
         "host_api_url": "http://192.168.1.5:6109"},
    ],
    "servers": [
        {"name": "Awesomation", "ok": True, "host_count": 1, "device_count": 1},
        {"name": "vpt-pi4", "ok": True, "host_count": 1, "device_count": 2},
        {"name": "gcloud-standalone", "ok": False, "error": "401", "host_count": 0, "device_count": 0},
    ],
}


class _Api:
    def __init__(self, hosts_reply=None, locks=None):
        self.calls = []
        self.hosts_reply = hosts_reply or MERGED
        self.locks = locks or {}

    def get(self, endpoint, params=None, headers=None):
        self.calls.append((endpoint, dict(params or {}), turn.target_url()))
        if endpoint == "/server/control/lockedDevices":
            return {"success": True, "locked_devices": self.locks}
        return self.hosts_reply


@pytest.fixture
def probes(monkeypatch):
    probed = []
    monkeypatch.setattr(device_tools.DeviceTools, "_check_host_reachable",
                        staticmethod(lambda url: probed.append(url) or True))
    return probed


def test_list_hosts_in_all_mode_shows_servers_failures_and_the_total(probes):
    api = _Api()
    t = _in_turn(scope="all")
    try:
        text = device_tools.DeviceTools(api).list_hosts({})["content"][0]["text"]
    finally:
        turn.reset_turn(t)
    assert api.calls[0][:2] == ("/server/system/getAllHosts", {"scope": "all"})
    assert "Server: vpt-pi4" in text and "Server: Awesomation" in text
    assert "gcloud-standalone: 401" in text
    assert "Platform total: 2 hosts, 3 devices (2 of 3 servers answered)" in text
    assert probes == ["http://10.0.0.1:6109"]   # only this server's own host is probed; vpt-pi4's status is trusted


def test_list_hosts_outside_a_turn_is_unchanged(probes):
    api = _Api({"success": True, "hosts": [{"host_name": "h", "status": "online", "devices": [],
                                           "host_api_url": "http://10.0.0.1:6109"}]})
    text = device_tools.DeviceTools(api).list_hosts({})["content"][0]["text"]
    assert api.calls[0][1] == {} and "Server:" not in text and "Platform total" not in text
    assert probes == ["http://10.0.0.1:6109"]


def test_list_hosts_for_another_server_reads_that_server_and_probes_nothing(probes):
    api = _Api({"success": True, "hosts": [{"host_name": "pi4-box", "status": "online", "devices": [],
                                           "host_api_url": "http://192.168.1.5:6109"}]})
    t = _in_turn(scope="vpt-pi4")
    try:
        with turn.use_target("vpt-pi4", "https://pi4.example.com"):
            text = device_tools.DeviceTools(api).list_hosts({})["content"][0]["text"]
    finally:
        turn.reset_turn(t)
    assert api.calls[0][2] == "https://pi4.example.com" and "Server: vpt-pi4" in text and probes == []


# ---- section 6: nothing reads this server's registry or lock table while the client points elsewhere --------------

@pytest.fixture
def local_state_forbidden(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("read this server's registry/lock table while pointed at another server")

    monkeypatch.setattr(server_utils, "get_host_manager", boom)
    monkeypatch.setattr(device_tools, "get_device_lock_info", boom)
    monkeypatch.setattr(screenshot_tools, "call_host", boom)
    monkeypatch.setattr(device_tools.DeviceTools, "_check_host_reachable", staticmethod(boom))


def test_device_info_takes_lock_state_from_the_owner_answer(local_state_forbidden):
    hosts = {"success": True, "hosts": [{"host_name": "pi4-box", "status": "online",
                                         "devices": [{"device_id": "device1", "device_name": "STB"}]}]}
    api = _Api(hosts, locks={"pi4-box:device1": {"owner_type": "manual_control", "owner_user_name": "Alex",
                                                  "lock_reason": "Take Control"}})
    t = _in_turn(scope="all")
    try:
        with turn.use_target("vpt-pi4", "https://pi4.example.com"):
            out = device_tools.DeviceTools(api).get_device_info({"host_name": "pi4-box"})
    finally:
        turn.reset_turn(t)
    text = out["content"][0]["text"]
    assert '"is_locked": true' in text and "Alex" in text and '"server": "vpt-pi4"' in text
    assert ("/server/control/lockedDevices", {}, "https://pi4.example.com") in api.calls


def test_device_info_in_all_mode_keys_locks_by_server(local_state_forbidden):
    api = _Api(locks={"vpt-pi4:pi4-box:device2": {"owner_type": "script_execution", "owner_user_name": "nightly"}})
    t = _in_turn(scope="all")
    try:
        out = device_tools.DeviceTools(api).get_device_info({"device_id": "device2"})
    finally:
        turn.reset_turn(t)
    assert api.calls[0][:2] == ("/server/system/getAllHosts", {"scope": "all"})
    assert ("/server/control/lockedDevices", {"scope": "all"}, None) in api.calls
    assert "nightly" in out["content"][0]["text"] and "vpt-pi4" in out["content"][0]["text"]


def test_device_info_outside_a_turn_still_uses_the_local_lock_table(monkeypatch):
    monkeypatch.setattr(device_tools, "get_device_lock_info", lambda h, d: {"owner_type": "manual_control"})
    api = _Api({"success": True, "hosts": [{"host_name": "h", "status": "online", "devices": [{"device_id": "d"}]}]})
    out = device_tools.DeviceTools(api).get_device_info({})
    assert '"is_locked": true' in out["content"][0]["text"] and len(api.calls) == 1


def test_localize_off_reads_the_owner_row(local_state_forbidden, monkeypatch):
    rows = {"hosts": [{"host_name": "pi4-box", "system_stats": {"monitoring_off": ["device3"]}}]}
    asked = []
    monkeypatch.setattr(turn, "get_json", lambda path, params=None, timeout=5: asked.append((path, params, turn.target_url())) or rows)
    t = _in_turn(scope="all")
    try:
        with turn.use_target("vpt-pi4", "https://pi4.example.com"):
            assert navigation_tools.NavigationTools._localize_off("pi4-box", "device3")
            assert navigation_tools.NavigationTools._localize_off("pi4-box", "device1") is None
    finally:
        turn.reset_turn(t)
    assert asked[0] == ("/server/system/getAllHosts", {"scope": "local"}, "https://pi4.example.com")


def test_screenshot_is_fetched_through_the_owner_server(local_state_forbidden, monkeypatch):
    asked = []

    def fake_bytes(path, params=None, timeout=10):
        asked.append((path, dict(params), turn.target_url()))
        return b"\xff\xd8\xffjpeg", None

    monkeypatch.setattr(turn, "get_bytes", fake_bytes)
    url = "/host/pi4-box/stream/capture1/captures/c.jpg?t=1"
    t = _in_turn(scope="all")
    try:
        with turn.use_target("vpt-pi4", "https://pi4.example.com"):
            content, reason = screenshot_tools._fetch_screenshot_bytes(url, "pi4-box")
    finally:
        turn.reset_turn(t)
    assert content == b"\xff\xd8\xffjpeg" and reason is None
    assert asked == [("/server/stream/hostFile",
                      {"host_name": "pi4-box", "path": "/host/pi4-box/stream/capture1/captures/c.jpg"},
                      "https://pi4.example.com")]


def test_host_file_route_relays_only_a_host_stream_path(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(server_stream_proxy_routes.server_stream_proxy_bp)
    monkeypatch.setattr(server_stream_proxy_routes, "get_host_manager",
                        lambda: SimpleNamespace(get_host=lambda n: {"host_name": n} if n == "pi4-box" else None))
    fetched = []
    monkeypatch.setattr(server_stream_proxy_routes, "call_host",
                        lambda host, path, **kw: fetched.append(path) or (b"\xff\xd8\xffX", 200))
    client = app.test_client()
    good = "/host/pi4-box/stream/capture1/captures/c.jpg"
    ok = client.get("/server/stream/hostFile", query_string={"host_name": "pi4-box", "path": good})
    assert ok.status_code == 200 and ok.mimetype == "image/jpeg" and fetched == [good]
    for host, path in [("pi4-box", "/host/pi4-box/system/health"), ("pi4-box", "/host/pi4-box/stream/../x"),
                       ("pi4-box", "/host/other/stream/a.jpg"), ("pi4-box", ""), ("ghost", "/host/ghost/stream/a.jpg")]:
        resp = client.get("/server/stream/hostFile", query_string={"host_name": host, "path": path})
        assert resp.status_code in (400, 404), (host, path)
    assert fetched == [good]


# ---- the credential stays out of logs, prompt and session ---------------------------------------------------------

def test_credential_stays_out_of_logs_prompt_and_session_context(caplog, platform):
    caplog.set_level(logging.DEBUG)
    args = server_agent_routes._turn_args({"turn_auth": {"token": SECRET, "auto_sign": "auto-sig-999"},
                                           "server_scope": "all", "host_name": "pi4-box",
                                           "selected_host_server": "vpt-pi4"})
    context = {"server_scope": args["scope"], "scope_line": server_agent_routes._scope_line(args["scope"])}
    assert context["scope_line"] == "Scope: all servers (Awesomation, vpt-pi1, vpt-pi4)"
    assert SECRET not in repr(context) and "auto-sig-999" not in repr(context)

    srv = _server_with(lambda p: {"content": [{"type": "text", "text": "ok"}], "isError": False})
    t = turn.bind_turn(**args["bind"])
    try:
        srv.handle_tool_call("probe", {"host_name": "pi4-box"})
        client = api_client_module.MCPAPIClient()
        assert client._auth()["Authorization"] == f"Bearer {SECRET}"   # the header is built, but...
    finally:
        turn.reset_turn(t)
    assert SECRET not in caplog.text and "auto-sig-999" not in caplog.text


def test_scope_line_forms():
    assert turn.scope_line("vpt-pi1", ["a"]) == "Scope: server vpt-pi1"
    assert turn.scope_line("", ["a"]) == ""
    assert turn.scope_line("all", []) == "Scope: all servers"


def test_tool_result_cache_key_depends_on_scope():
    from backend_server.src.agent.core.tool_bridge import ToolResultCache
    cache = ToolResultCache()
    plain = cache._make_key("list_hosts", {})
    t = _in_turn(scope="all")
    try:
        in_all = cache._make_key("list_hosts", {})
    finally:
        turn.reset_turn(t)
    t = _in_turn(scope="vpt-pi4")
    try:
        in_one = cache._make_key("list_hosts", {})
    finally:
        turn.reset_turn(t)
    assert len({plain, in_all, in_one}) == 3
