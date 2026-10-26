"""Atlas quick step (TASK-140 Q1-Q6): pool, eligibility, learned quick set, device rule, and the manager hook.

Pure unit tests: no LLM, no database (the stats loader and the counters are injected, the model call is faked)."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))

try:
    from agent import quick_step as qs  # noqa: E402
    from agent.core.manager import QAManagerAgent  # noqa: E402
    from agent.core.message_types import EventType  # noqa: E402
    from agent.core.session import Session  # noqa: E402
    from shared.src.lib.ai import router as ai_router  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit

ALLOWED = list(qs.POOL)


# ------------------------------------------------------------------ pool and eligibility

def test_pool_has_no_write_or_run_tools_and_base_is_in_pool():
    assert not [t for t in qs.POOL if t.startswith(("delete_", "create_", "update_", "save_", "execute_"))]
    assert set(qs.BASE) <= set(qs.POOL)


@pytest.mark.parametrize("message,expected", [
    ("open the heatmap", True),
    ("take control of stb1", True),
    ("prends le contrôle de stb1", True),
    ("what is on stb1", False),
    ("take control of stb1?", False),
    ("Is stb1 free", False),
    ("comment va stb1", False),
    ("wie spät ist es", False),
    ("one two three four five six seven eight nine ten eleven twelve thirteen", False),
    ("", False),
])
def test_eligible(message, expected):
    assert qs.eligible(message) is expected


def test_kill_switch(monkeypatch):
    assert qs.enabled()
    monkeypatch.setenv("ATLAS_QUICK_STEP", "off")
    assert not qs.enabled()


# ------------------------------------------------------------------ learned quick set

def _rows(**tools):
    return {t: {"uses": u, "hits": h, "misses": m} for t, (u, h, m) in tools.items()}


def test_quick_tools_base_plus_top_by_uses():
    mine = _rows(list_hosts=(10, 0, 0), search_docs=(6, 0, 0), release_control=(1, 0, 0))
    out = qs.quick_tools("t", "u", ALLOWED, load_user=lambda t, u: mine, load_team=lambda t: {})
    assert out == list(qs.BASE) + ["list_hosts", "search_docs", "release_control"]


def test_quick_tools_new_user_gets_team_tools():
    team = _rows(search_videos=(40, 0, 0), list_hosts=(20, 0, 0))
    out = qs.quick_tools("t", "u", ALLOWED, load_user=lambda t, u: _rows(list_hosts=(2, 0, 0)), load_team=lambda t: team)
    assert out == list(qs.BASE) + ["search_videos", "list_hosts"]


def test_quick_tools_cap_and_allowed():
    mine = {t: {"uses": 50 - i, "hits": 0, "misses": 0} for i, t in enumerate(t for t in qs.POOL if t not in qs.BASE)}
    out = qs.quick_tools("t", "u", ALLOWED, load_user=lambda t, u: mine, load_team=lambda t: {})
    assert len(out) == qs.QUICK_CAP and out[:len(qs.BASE)] == list(qs.BASE)
    narrow = qs.quick_tools("t", "u", ["take_control", "list_hosts"], load_user=lambda t, u: mine, load_team=lambda t: {})
    assert narrow == ["take_control", "list_hosts"]


def test_demotion_needs_three_misses_and_rate_over_30_percent():
    assert not qs.is_demoted({"hits": 0, "misses": 2})
    assert qs.is_demoted({"hits": 5, "misses": 3})        # 3/8 = 37%
    assert not qs.is_demoted({"hits": 20, "misses": 3})   # 3/23 = 13%
    mine = _rows(list_hosts=(10, 5, 3), search_docs=(6, 0, 0))
    out = qs.quick_tools("t", "u", ALLOWED, load_user=lambda t, u: mine, load_team=lambda t: {})
    assert "list_hosts" not in out and "search_docs" in out


# ------------------------------------------------------------------ schema and device rule

DEVICES = [{"device_name": "stb1", "host_name": "h1", "device_id": "device1"},
           {"device_name": "stb2", "host_name": "h1", "device_id": "device2"},
           {"device_name": "dup", "host_name": "h2", "device_id": "device1"},
           {"device_name": "dup", "host_name": "h3", "device_id": "device9"}]
SCHEMA = {"type": "object", "properties": {"host_name": {"type": "string"}, "device_id": {"type": "string"}},
          "required": ["host_name", "device_id"]}


def test_device_rule_never_substitutes():
    assert qs.check_devices({"host_name": "h1", "device_id": "device1"}, DEVICES) is None
    assert qs.check_devices({"host_name": "h1", "device_id": "device7"}, DEVICES)      # unknown
    assert qs.check_devices({"device_id": "device1"}, DEVICES)                          # two hosts: ambiguous
    assert qs.check_devices({"device_name": "dup"}, DEVICES)                            # two devices: ambiguous
    assert qs.check_devices({"device_name": "stb2"}, DEVICES) is None
    assert qs.check_devices({"device_id": "device1"}, [])


def test_validate_pick():
    schemas = {"take_control": SCHEMA}
    ok = {"host_name": "h1", "device_id": "device1"}
    assert qs.validate_pick("take_control", ok, ["take_control"], schemas, DEVICES) is None
    assert qs.validate_pick("take_control", ok, ["list_hosts"], schemas, DEVICES)          # not in the quick set
    assert qs.validate_pick("take_control", {"host_name": "h1"}, ["take_control"], schemas, DEVICES)  # missing
    assert qs.validate_pick("take_control", {**ok, "x": 1}, ["take_control"], schemas, DEVICES)       # unknown arg
    assert qs.validate_pick("take_control", {"host_name": "h1", "device_id": "nope"}, ["take_control"], schemas, DEVICES)


# ------------------------------------------------------------------ manager hook

def _install_router():
    ai_router.set_snapshot_for_tests({
        "endpoints": {"e": {"id": "e", "name": "openrouter", "preset": "openrouter", "enabled": True, "allowed_team_ids": []}},
        "profiles": {"p": {"id": "p", "name": "primary", "model": "m", "endpoint_id": "e", "enabled": True,
                           "capabilities": ["text"]}},
        "routes": [{"id": "r", "usage_key": "agent.atlas", "team_id": None, "profile_id": "p", "enabled": True,
                    "priority": 100}],
    })


def _response(*blocks):
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=10, output_tokens=2))


def _tool_use(name, **args):
    return SimpleNamespace(type="tool_use", id="tu1", name=name, input=args)


@pytest.fixture
def agent(monkeypatch):
    _install_router()
    session = Session(id="s1")
    session.context.update(team_id="team-1", user_id="user-1", available_devices=DEVICES)
    mgr = QAManagerAgent(user_identifier="team-1", session=session)
    counted = []
    monkeypatch.setattr(qs, "record", lambda kind, team, user, tool: counted.append((kind, tool)))
    monkeypatch.setattr(qs, "quick_tools", lambda team, user, allowed, **_kw: ["take_control", "list_hosts"])
    monkeypatch.setattr(mgr, "_select_router_tools_for_message", lambda m: list(qs.POOL))
    monkeypatch.setattr(mgr, "_quick_schemas", lambda names: {"take_control": SCHEMA, "list_hosts": {"type": "object", "properties": {}}})
    monkeypatch.setattr(mgr, "_quick_description", lambda n: "")
    mgr.counted, mgr.session = counted, session
    yield mgr
    ai_router.set_snapshot_for_tests(None)


def _run(agent, message):
    async def go():
        return [e async for e in agent._quick_step(message, agent.session)]
    return asyncio.run(go())


def test_quick_step_runs_tool_and_ends_turn(agent, monkeypatch):
    ran = []
    monkeypatch.setattr(agent, "_create_turn", lambda kw: _response(_tool_use("take_control", host_name="h1", device_id="device2")))
    monkeypatch.setattr(agent.tool_bridge, "execute",
                        lambda name, params, allowed_tools=None, cache_config=None: ran.append((name, params)) or {"content": [{"type": "text", "text": "locked"}]})
    monkeypatch.setattr(agent.tool_bridge, "companion_fallback", lambda: None)
    events = _run(agent, "take control of stb2")
    assert [e.type for e in events] == [EventType.TOOL_CALL, EventType.TOOL_RESULT, EventType.MESSAGE, EventType.SESSION_ENDED]
    assert ran == [("take_control", {"host_name": "h1", "device_id": "device2"})]
    assert agent._quick_handled
    assert agent.session.messages[-1]["role"] == "assistant" and "take_control" in agent.session.messages[-1]["content"]
    assert agent.counted == [("hit", "take_control")]


def test_ask_atlas_continues_the_normal_turn(agent, monkeypatch):
    monkeypatch.setattr(agent, "_create_turn", lambda kw: _response(_tool_use("ask_atlas")))
    agent._quick_handled = False
    assert _run(agent, "list the failing scripts and rerun them") == []
    assert not agent._quick_handled and agent.counted == []


def test_unknown_device_is_a_miss_and_not_executed(agent, monkeypatch):
    """Never executed; since TASK-175 the turn says the device is not there instead of a model hunt."""
    monkeypatch.setattr(agent, "_create_turn", lambda kw: _response(_tool_use("take_control", host_name="h1", device_id="device7")))
    monkeypatch.setattr(agent.tool_bridge, "execute", lambda *a, **k: pytest.fail("must not run"))
    agent._quick_handled = False
    events = _run(agent, "take control of stb7")
    assert [e.type for e in events] == [EventType.MESSAGE, EventType.SESSION_ENDED]
    assert "can't find a device" in events[0].content and "h1/device7" in events[0].content
    assert agent._quick_handled and agent.counted == [("miss", "take_control")]


def test_tool_outside_quick_set_is_a_miss(agent, monkeypatch):
    monkeypatch.setattr(agent, "_create_turn", lambda kw: _response(_tool_use("delete_node", id="x")))
    agent._quick_handled = False
    assert _run(agent, "remove that node") == []
    assert agent.counted == [("miss", "delete_node")]


def test_failed_tool_counts_a_miss_and_still_ends_the_turn(agent, monkeypatch):
    monkeypatch.setattr(agent, "_create_turn", lambda kw: _response(_tool_use("take_control", host_name="h1", device_id="device1")))
    monkeypatch.setattr(agent.tool_bridge, "execute", lambda *a, **k: {"isError": True, "content": [{"type": "text", "text": "locked by bob"}]})
    monkeypatch.setattr(agent.tool_bridge, "companion_fallback", lambda: None)
    events = _run(agent, "take control of stb1")
    assert events[1].success is False and events[-1].type == EventType.SESSION_ENDED
    assert agent.counted == [("miss", "take_control")]


def test_voice_hint_skips_the_model_call_and_is_consumed(agent, monkeypatch):
    monkeypatch.setattr(agent, "_create_turn", lambda kw: pytest.fail("no model call for a valid hint"))
    monkeypatch.setattr(agent.tool_bridge, "execute", lambda *a, **k: {"content": [{"type": "text", "text": "ok"}]})
    monkeypatch.setattr(agent.tool_bridge, "companion_fallback", lambda: None)
    agent.session.context["quick_hint"] = {"tool": "take_control", "args": {"host_name": "h1", "device_id": "device2"}}
    events = _run(agent, "prends le contrôle de stb2 s'il te plaît merci beaucoup vraiment très vite maintenant")
    assert events[-1].type == EventType.SESSION_ENDED and "quick_hint" not in agent.session.context


def test_invalid_voice_hint_falls_back_to_the_model(agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "_create_turn", lambda kw: calls.append(kw) or _response(_tool_use("ask_atlas")))
    agent.session.context["quick_hint"] = {"tool": "take_control", "args": {"host_name": "h1", "device_id": "ghost"}}
    agent._quick_handled = False
    assert _run(agent, "take control of ghost") == []
    assert len(calls) == 1 and calls[0]["max_tokens"] == 400
    assert [t["name"] for t in calls[0]["tools"]] == ["take_control", "list_hosts", "ask_atlas"]


def test_quick_call_is_tracked_under_its_own_usage(agent, monkeypatch):
    seen = []
    monkeypatch.setattr(agent, "_create_turn", lambda kw: seen.append(agent.usage_key) or _response(_tool_use("ask_atlas")))
    _run(agent, "open the heatmap")
    assert seen == ["agent.atlas.quick"] and agent.usage_key == "agent.atlas"


def test_not_eligible_message_does_nothing(agent, monkeypatch):
    monkeypatch.setattr(agent, "_create_turn", lambda kw: pytest.fail("no call for a question"))
    assert _run(agent, "what is on stb1?") == []


def test_summary_line_is_plain_text():
    assert qs.summary_line("show_page", {"page": "heatmap"}, {"result": "Offered the Heatmap"}) == "Opened heatmap. Offered the Heatmap"
    assert "{" not in qs.summary_line("take_control", {"host_name": "h", "device_id": "d"},
                                      {"content": [{"type": "text", "text": "Control taken"}]})


def test_hidden_mcp_tools_pass_the_existence_check():
    from agent.core.tool_bridge import ToolBridge
    bridge = ToolBridge()
    assert set(bridge.mcp_server.HIDDEN_TOOLS) <= set(bridge.get_available_tool_names() + sorted(bridge.mcp_server.HIDDEN_TOOLS))
    # It reaches the real take_control (which then wants its arguments), not "does not exist".
    with pytest.raises(ValueError, match="host_name and device_id are required"):
        bridge.execute("take_control", {}, allowed_tools=["take_control"])


def test_info_tool_must_fit_the_message():
    """TASK-163: 'Screenshot <device>' was answered with the page list; an info tool needs its subject in the message."""
    devices = [{"device_name": "Phone slot 1", "host_name": "h", "device_id": "d"}]
    assert not qs.fits("get_available_pages", "Dump the UI elements of Phone slot 1", devices)
    assert not qs.fits("list_hosts", "Screenshot Phone slot 1 on host-clone-1", devices)
    assert not qs.fits("get_execution_results", "Take a screenshot of all stb", [])
    assert qs.fits("get_available_pages", "which pages are there", [])
    assert qs.fits("list_hosts", "list all devices", [])
    assert qs.fits("capture_screenshot", "screenshot Phone slot 1", devices)
    assert not qs.fits("show_page", "Show me what Phone slot 1 is displaying", devices)
    assert qs.fits("show_page", "Open the heatmap for Phone slot 1", devices)
    assert qs.fits("show_page", "show the dashboard", devices)
    assert not qs.fits("take_control", "Take a screenshot of Phone slot 1", devices)
    assert qs.fits("take_control", "Take control of Phone slot 1", devices)
