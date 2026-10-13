"""
Deterministic reproduction of MiniMax response quirks in QAManagerAgent.

These bugs only fire probabilistically through the real LLM (~30% of runs),
which makes "run the chat N times" a weak regression guard. Here the exact
malformed responses are synthesized, so each failure mode triggers 100% of
the time and the manager's handling is asserted directly — no LLM, no server.

Covered quirks (all observed live on feat/demo, 2026-07-22/23):
1. Parallel tool_use blocks despite disable_parallel_tool_use → only the first
   may be recorded in history (else next call fails MiniMax error 2013).
2. `LOAD SKILL` emitted as a tool_use block instead of the text command →
   must be honored as a skill load, not executed as a (nonexistent) tool.
3. Thinking-only turn with no user-visible text → retried with a nudge, not
   surfaced as an "Empty response" error.
4. require_tool_use skills reject a final answer produced with zero tool calls.

Run: pytest tests/backend_server/test_agent_minimax_quirks.py -v
(no SERVER_URL needed — pure unit tests)
"""

import asyncio
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))
sys.path.insert(0, str(REPO / "shared" / "lib"))


# The agent stack pulls in the server's runtime deps (anthropic, redis, langfuse, …). CI's
# backend job installs only pytest/requests, so skip this module there instead of aborting
# the whole collection ("1 error during collection" took every other test down with it).
try:
    from agent.core.manager import QAManagerAgent  # noqa: E402
    from agent.core.message_types import EventType  # noqa: E402
    from agent.core.session import Session  # noqa: E402
    from shared.src.lib.ai.router import Hop  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Fake Anthropic-protocol objects
# --------------------------------------------------------------------------

class Blk:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def text_b(t):
    return Blk(type="text", text=t)


def think_b(t):
    return Blk(type="thinking", thinking=t)


def tool_b(name, inp=None, bid="tu_1"):
    return Blk(type="tool_use", name=name, input=inp or {}, id=bid)


class Usage:
    input_tokens = 10
    output_tokens = 5


class Resp:
    def __init__(self, blocks, stop="end_turn"):
        self.content = blocks
        self.usage = Usage()
        self.stop_reason = stop


class StubMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, **kw):
        self.requests.append(kw)
        if not self.responses:
            raise AssertionError("Manager made more LLM calls than the test scripted")
        return self.responses.pop(0)


class StubClient:
    def __init__(self, responses):
        self.messages = StubMessages(responses)


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

@pytest.fixture()
def make_manager(monkeypatch):
    def _make(responses):
        session = Session(id="test-session")
        manager = QAManagerAgent(user_identifier="test", agent_id="assistant", session=session)
        stub = StubClient(responses)
        monkeypatch.setattr(QAManagerAgent, "client", property(lambda self: stub))
        monkeypatch.setattr(QAManagerAgent, "provider", property(lambda self: "minimax"))
        monkeypatch.setattr(QAManagerAgent, "model", property(lambda self: "minimax-m2.7-highspeed"))
        hop = Hop(profile={"name": "minimax-fast", "model": "minimax-m2.7-highspeed"}, endpoint={"preset": "minimax"})
        resolution = SimpleNamespace(primary=hop, hops=[hop], is_fallback=lambda h: False)
        monkeypatch.setattr(QAManagerAgent, "_resolution", lambda self: resolution)
        # No AI routing tables in unit tests: the routed profile is stubbed above.
        monkeypatch.setattr(QAManagerAgent, "api_key_configured", property(lambda self: True))
        manager.tool_bridge.execute = (
            lambda name, inp, **kw: {"content": [{"type": "text", "text": "tool-ok"}]}
        )
        return manager, stub, session

    return _make


def run_chat(manager, session, message):
    async def _collect():
        events = []
        async for ev in manager.process_message(message, session):
            events.append(ev)
        return events

    return asyncio.run(_collect())


def event_types(events):
    return [e.type for e in events]


def errors(events):
    return [e for e in events if e.type == EventType.ERROR]


# Neutral message: must not contain any search-docs trigger words
# ("what", "how", "doc", "api", "free", "cost", ...) to keep router mode.
NEUTRAL_MSG = "hello there friend"


# --------------------------------------------------------------------------
# 1. Parallel tool_use blocks
# --------------------------------------------------------------------------

def test_parallel_tool_use_records_only_first(make_manager):
    manager, stub, session = make_manager([
        Resp([
            text_b("Checking two things at once."),
            tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_a"),
            tool_b("search_docs", {"query": "trees"}, bid="tu_b"),
        ], stop="tool_use"),
        Resp([text_b("Final answer.")]),
    ])

    events = run_chat(manager, session, NEUTRAL_MSG)

    assert not errors(events), f"unexpected errors: {[e.content for e in errors(events)]}"
    # The second LLM request replays history: its assistant turn must contain
    # exactly ONE tool_use block, and exactly one matching tool_result.
    second_request = stub.messages.requests[1]["messages"]
    assistant_turns = [m for m in second_request if m["role"] == "assistant"]
    recorded_tool_uses = [
        b for m in assistant_turns for b in m["content"]
        if getattr(b, "type", None) == "tool_use"
    ]
    assert len(recorded_tool_uses) == 1
    assert recorded_tool_uses[0].id == "tu_a"
    tool_results = [
        b for m in second_request if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert [b["tool_use_id"] for b in tool_results] == ["tu_a"]
    assert any(e.type == EventType.MESSAGE and "Final answer." in (e.content or "") for e in events)


# --------------------------------------------------------------------------
# 2. LOAD SKILL emitted as a tool_use block
# --------------------------------------------------------------------------

def test_load_skill_as_tool_use_loads_skill(make_manager):
    manager, stub, session = make_manager([
        Resp([tool_b("LOAD SKILL", {"skill": "search-docs"})], stop="tool_use"),
        Resp([tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_r")], stop="tool_use"),
        Resp([text_b("Docs say hi.")]),
    ])

    events = run_chat(manager, session, NEUTRAL_MSG)

    assert not errors(events), f"unexpected errors: {[e.content for e in errors(events)]}"
    assert any(e.type == EventType.SKILL_LOADED and e.content == "search-docs" for e in events)
    assert manager._active_skill is not None and manager._active_skill.name == "search-docs"
    # The protocol must stay consistent: the LOAD SKILL tool_use got a tool_result.
    second_request = stub.messages.requests[1]["messages"]
    tool_results = [
        b for m in second_request if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"
    ]
    assert any(b["tool_use_id"] == "tu_1" for b in tool_results)
    assert any(e.type == EventType.MESSAGE and "Docs say hi." in (e.content or "") for e in events)


def test_load_skill_as_text_never_ends_request_on_assistant(make_manager):
    """After a text `LOAD SKILL x` reply the next request must end on a user turn:
    ending on the assistant turn is a prefill, which Claude (Sonnet 5 via
    OpenRouter) rejects with 400 — every Sonnet chat that loaded a skill died
    (BUG-0177)."""
    manager, stub, session = make_manager([
        Resp([text_b("LOAD SKILL search-docs")]),
        Resp([tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_r")], stop="tool_use"),
        Resp([text_b("Docs say hi.")]),
    ])

    events = run_chat(manager, session, NEUTRAL_MSG)

    assert not errors(events), f"unexpected errors: {[e.content for e in errors(events)]}"
    # The stub keeps a reference to the live history, so find the LOAD SKILL turn
    # and check what follows it rather than reading the list's current tail.
    history = stub.messages.requests[1]["messages"]
    load_turn = next(i for i, m in enumerate(history) if m["role"] == "assistant"
                     and any(getattr(b, "text", "") == "LOAD SKILL search-docs" for b in m["content"]))
    follow_up = history[load_turn + 1]
    assert follow_up["role"] == "user"
    assert "search-docs" in follow_up["content"]


# --------------------------------------------------------------------------
# 3. Thinking-only turn with no visible text
# --------------------------------------------------------------------------

def test_thinking_only_response_retries_not_errors(make_manager):
    manager, stub, session = make_manager([
        Resp([think_b("pondering silently...")]),
        Resp([text_b("Recovered answer.")]),
    ])

    events = run_chat(manager, session, NEUTRAL_MSG)

    assert not errors(events), f"unexpected errors: {[e.content for e in errors(events)]}"
    assert any(e.type == EventType.MESSAGE and "Recovered answer." in (e.content or "") for e in events)
    # The retry nudge must be in the second request's history.
    second_request = stub.messages.requests[1]["messages"]
    assert any(
        m["role"] == "user" and isinstance(m["content"], str)
        and "no user-visible text" in m["content"]
        for m in second_request
    )


def test_persistent_empty_response_errors_after_retries(make_manager):
    manager, stub, session = make_manager([
        Resp([think_b("...")]),
        Resp([think_b("...")]),
        Resp([think_b("...")]),
    ])

    events = run_chat(manager, session, NEUTRAL_MSG)

    errs = errors(events)
    assert len(errs) == 1 and "Empty response" in errs[0].content
    assert len(stub.messages.requests) == 3  # 1 original + 2 retries, then give up


# --------------------------------------------------------------------------
# Router tool selection must always offer the docs tools
# --------------------------------------------------------------------------

def test_router_tools_always_include_read_doc(make_manager):
    """The router rules tell the model to read_doc(INDEX.md) for platform
    questions — so read_doc must be offered even when the message's keywords
    fill the 12-tool quota with something else. Observed live: 'what is a
    navigation tree' selected only navigation tools and the model flailed
    into crawl_app/list_navigation_nodes and errored (runs 6/8/14/20 of the
    2026-07-23 20-run batch)."""
    manager, _, _ = make_manager([])
    for msg in (
        "what is a navigation tree",
        "hello there friend",
        "tell me about campaign execution on devices",
    ):
        selected = manager._select_router_tools_for_message(msg)
        assert "read_doc" in selected, f"read_doc missing for {msg!r}: {selected}"
        assert len(selected) <= 14


def test_router_tools_include_prerequisites(make_manager):
    """A router tool is offered with the tool that feeds it (BUG-0170):
    'open YouTube ... search' scored analyze_screen_for_action and
    execute_device_action but not dump_ui_elements / list_actions, so the
    model sent elements=[] and guessed the web command type_text."""
    manager, _, _ = make_manager([])
    msg = ('Open YouTube in the browser, search for "Raspberry Pi" and tell me '
           'the title of the first result.')
    selected = manager._select_router_tools_for_message(msg)
    assert len(selected) <= 12
    assert "read_doc" in selected
    for tool, prereqs in manager._ATLAS_ROUTER_TOOL_PREREQUISITES.items():
        if tool in selected:
            for prereq in prereqs:
                assert prereq in selected, f"{tool} offered without {prereq}: {selected}"
    assert "analyze_screen_for_action" in selected
    assert "dump_ui_elements" in selected


# --------------------------------------------------------------------------
# 4. require_tool_use rejects toolless final answers
# --------------------------------------------------------------------------

def test_require_tool_use_rejects_toolless_answer(make_manager):
    manager, stub, session = make_manager([
        Resp([text_b("Pricing is not covered in the docs, contact sales.")]),
        Resp([tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_r")], stop="tool_use"),
        Resp([text_b("It is free under the MIT license.")]),
    ])
    assert manager.load_skill("search-docs"), "search-docs skill must exist"

    events = run_chat(manager, session, NEUTRAL_MSG)

    assert not errors(events), f"unexpected errors: {[e.content for e in errors(events)]}"
    # The toolless refusal must NOT be the final message.
    messages = [e.content for e in events if e.type == EventType.MESSAGE]
    assert messages, "expected a final message"
    assert "MIT license" in messages[-1]
    # The rejection nudge must be in the second request.
    second_request = stub.messages.requests[1]["messages"]
    assert any(
        m["role"] == "user" and isinstance(m["content"], str)
        and "without consulting any tool" in m["content"]
        for m in second_request
    )


def test_router_offers_analytics_core_tools_for_analytics_questions(make_manager):
    """TASK-43 acceptance prompts must reach the analytics layer. Observed live on
    the first deploy: 'show failing testcases for this device' and 'show degraded
    hosts' scored only device/testcase tools, so Atlas answered from list_testcases
    and get_device_info instead of render_analytics_artifact."""
    manager, _, _ = make_manager([])
    core = {"list_analytics_sources", "query_analytics_data", "render_analytics_artifact"}
    for msg in (
        "show failing testcases for this device",
        "compare pass rate by device",
        "show degraded hosts",
        "provide the last known KPI radar for userinterface stb_tv",
        "compare v1 and v2 KPI for stb_tv over the last 30 days",
        "show only regressions over 10%",
        "build a canvas with pass rate, duration trend, and failing cases for these two devices",
    ):
        selected = manager._select_router_tools_for_message(msg)
        assert core <= set(selected), f"analytics tools missing for {msg!r}: {selected}"
        assert "read_doc" in selected and len(selected) <= 14
    plain = manager._select_router_tools_for_message("navigate to the home screen")
    assert not core & set(plain)


def test_router_offers_grafana_and_export_only_when_asked(make_manager):
    """Live smoke: asked for KPI regressions, Atlas wrote a Grafana draft nobody requested."""
    manager, _, _ = make_manager([])
    for msg in ("show only regressions over 10%", "compare pass rate by device", "show degraded hosts"):
        selected = set(manager._select_router_tools_for_message(msg))
        assert not selected & {"create_grafana_draft", "export_analytics_data"}, msg
    assert "create_grafana_draft" in manager._select_router_tools_for_message("make a Grafana version of the pass rate chart")
    assert "export_analytics_data" in manager._select_router_tools_for_message("export the pass rate by device as CSV")


# ---------------------------------------------------------------------------
# TASK-43 W4: a canvas "for my selected devices" must be built, not asked about
# ---------------------------------------------------------------------------

CANVAS_PROMPT = ("Build a canvas with 3 panels for my selected devices: pass rate by device, "
                 "KPI averages, and incidents over the last 7 days")


def test_canvas_prompt_is_offered_the_analytics_tools(make_manager):
    manager, _, _ = make_manager([])
    selected = manager._select_router_tools_for_message(CANVAS_PROMPT)
    for tool in ("list_analytics_sources", "query_analytics_data", "render_analytics_artifact"):
        assert tool in selected


def _router_prompt(manager, ctx):
    tools = manager._select_router_tools_for_message(CANVAS_PROMPT)
    return manager._build_router_prompt(ctx, CANVAS_PROMPT, tools)


def test_router_prompt_names_selected_device_and_forbids_asking(make_manager):
    manager, _, _ = make_manager([])
    fleet = [{"host_name": f"h{i}", "device_id": f"d{i}", "device_name": f"dev{i}"} for i in range(30)]
    ctx = {"host_name": "h25", "device_id": "d25", "available_devices": fleet}
    prompt = _router_prompt(manager, ctx)
    # the selected device is named and listed although it is beyond the first 10 of 30
    assert "device_name='dev25'" in prompt
    assert "dev25 (host_name='h25'" in prompt
    assert "scope='current_device'" in prompt
    assert "Never ask which devices" in prompt


def test_router_prompt_without_selection_defaults_to_visible_scope(make_manager):
    manager, _, _ = make_manager([])
    prompt = _router_prompt(manager, {})
    assert "no device is selected" in prompt
    assert "scope='visible'" in prompt
    assert "Never ask which devices" in prompt
    assert "NEVER reply with a question" in prompt


def test_router_prompt_foreign_device_uses_visible_scope(make_manager):
    manager, _, _ = make_manager([])
    ctx = {"host_name": "host-clone-1", "device_id": "host", "selected_server_hosts": ["pi-host-1", "pi-host-2"]}
    prompt = _router_prompt(manager, ctx)
    assert "NOT a valid analytics selection" in prompt
    assert "never pass scope='current_device'" in prompt
    assert "Never ask which devices" in prompt


def test_router_prompt_device_on_selected_server_keeps_current_device_scope(make_manager):
    manager, _, _ = make_manager([])
    ctx = {"host_name": "pi-host-1", "device_id": "d1", "selected_server_hosts": ["pi-host-1"]}
    prompt = _router_prompt(manager, ctx)
    assert "scope='current_device'" in prompt
    assert "NOT a valid analytics selection" not in prompt


@pytest.mark.parametrize("ctx", [
    {},
    {"host_name": "pi-host-1", "device_id": "d1", "selected_server_hosts": ["pi-host-1"]},
    {"host_name": "host-clone-1", "device_id": "host", "selected_server_hosts": ["pi-host-1"]},
])
def test_router_prompt_forbids_substituting_named_devices(make_manager, ctx):
    manager, _, _ = make_manager([])
    prompt = _router_prompt(manager, ctx)
    assert 'filters={"device_name": [...]}' in prompt
    assert "never substitute other devices" in prompt
    assert "never title the result after devices the user did not ask for" in prompt


def test_router_prompt_says_a_canvas_is_one_call_with_panels(make_manager):
    manager, _, _ = make_manager([])
    prompt = _router_prompt(manager, {})
    assert "ONE render_analytics_artifact call with panels=[...]" in prompt
    assert "never one call per chart" in prompt


def test_render_tool_docstring_and_shown_reply_say_one_call_for_several_charts():
    from backend_server.src.mcp.tools import analytics_tools as at
    assert "ONE call with panels=[...]" in at.AnalyticsTools.render_analytics_artifact.__doc__
    assert "once per requested chart" not in at.AnalyticsTools.render_analytics_artifact.__doc__
    spec = {"kind": "visualization", "title": "T", "mark": "bar", "options": {},
            "data": {"rows": [{"a": 1}], "row_count": 1}}
    assert "ONE call with panels=[...]" in at._shown({"content_data": {"artifact_spec": spec}})
    canvas = {"kind": "canvas", "panels": [spec, spec]}
    assert "ONE call with panels=[...]" not in at._shown({"content_data": {"artifact_spec": canvas}})


def test_user_named_devices_are_recorded_and_put_in_the_router_prompt(make_manager):
    manager, _, session = make_manager([])
    fleet = [{"host_name": "rpi1-host", "device_id": "d1", "device_name": "S21x"},
             {"host_name": "other-host", "device_id": "d2", "device_name": "Phone slot 1"},
             {"host_name": "rpi1-host", "device_id": "host", "device_name": "host"}]
    session.context.update({"available_devices": fleet, "selected_server_hosts": ["rpi1-host"],
                            "selected_server_name": "RPI1-server"})
    manager._record_named_devices("pass rate for phone slot 1 and S21x on all hosts", session)
    assert {d["name"]: d["on_server"] for d in session.context["named_devices"]} == {"Phone slot 1": False, "S21x": True}
    prompt = _router_prompt(manager, dict(session.context))
    assert "User named devices:" in prompt
    assert "'Phone slot 1' (not on the selected server RPI1-server)" in prompt
    assert "'S21x' (on this server)" in prompt
    # next message names nothing: reset, no line
    manager._record_named_devices("how are things", session)
    assert session.context["named_devices"] == []
    assert "User named devices:" not in _router_prompt(manager, dict(session.context))


# ---------------------------------------------------------------------------
# TASK-43 phase 10: "create a dashboard" loads the grafana-dashboard skill
# ---------------------------------------------------------------------------

def test_create_dashboard_requests_load_the_grafana_dashboard_skill(make_manager):
    for message in ("create a Grafana dashboard with pass rate by device and incidents over time",
                    "create a dashboard of KPI by variant"):
        manager, stub, session = make_manager([
            Resp([tool_b("create_grafana_draft", {"title": "T", "panels": [{"preset": "pass_rate_trend"}]})], stop="tool_use"),
            Resp([text_b("Here is your dashboard.")]),
        ])
        calls = []
        manager.tool_bridge.execute = lambda name, inp, **kw: calls.append(name) or {"content": [{"type": "text", "text": "ok"}]}
        events = run_chat(manager, session, message)
        assert not errors(events), [e.content for e in errors(events)]
        assert manager._active_skill is not None and manager._active_skill.name == "grafana-dashboard", message
        assert calls == ["create_grafana_draft"]
        offered = {t["name"] for t in stub.messages.requests[0]["tools"]}
        assert offered == {"list_analytics_sources", "describe_analytics_source", "create_grafana_draft",
                           "render_analytics_artifact"}


def test_opening_the_dashboard_page_does_not_load_the_dashboard_skill(make_manager):
    for message in ("open the dashboard page", "show me the dashboard page", "navigate to the Dashboard"):
        manager, stub, session = make_manager([Resp([text_b("Opening it.")])])
        run_chat(manager, session, message)
        assert manager._active_skill is None, message


def test_grafana_dashboard_skill_definition_loads(make_manager):
    manager, _, _ = make_manager([])
    assert "grafana-dashboard" in manager.agent_config["available_skills"]
    assert manager.load_skill("grafana-dashboard")
    skill = manager._active_skill
    assert skill.require_tool_use and "ONCE" in skill.system_prompt
    assert "create_grafana_draft" in skill.tools
    assert "never write sql" in skill.system_prompt.lower()


def test_selected_device_reference_is_recorded_per_message(make_manager):
    manager, _, session = make_manager([])
    session.context.update({"host_name": "rpi1-host", "device_id": "host", "selected_server_hosts": ["rpi1-host"],
                            "available_devices": [{"host_name": "rpi1-host", "device_id": "host", "device_name": "host"}]})
    manager._record_named_devices("canvas for my selected devices", session)
    assert session.context["refers_to_selected_device"] is True
    assert session.context["selected_device"]["device_name"] == "host"
    manager._record_named_devices("pass rate by device", session)
    assert session.context["refers_to_selected_device"] is False
    session.context["selected_server_hosts"] = ["labox-tv"]
    manager._record_named_devices("on my device", session)
    assert session.context["refers_to_selected_device"] is False and session.context["selected_device_foreign"] is True


# --------------------------------------------------------------------------
# Profile extra JSON reaches agent turns (effort per profile)
# --------------------------------------------------------------------------

def test_profile_extra_is_sent_on_agent_turns(make_manager):
    manager, _stub, _session = make_manager([])
    hop = Hop(profile={"name": "atlas", "model": "claude-haiku-5-5",
                       "extra": {"output_config": {"effort": "low"}}},
              endpoint={"preset": "anthropic"})
    kwargs = manager._turn_kwargs(hop, {"max_tokens": 10})
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["extra_body"] == {"output_config": {"effort": "low"}}


def test_empty_profile_extra_sends_no_extra_body(make_manager):
    manager, _stub, _session = make_manager([])
    hop = Hop(profile={"name": "mm", "model": "minimax-m2.7-highspeed"}, endpoint={"preset": "minimax"})
    kwargs = manager._turn_kwargs(hop, {"max_tokens": 10})
    assert kwargs["extra_body"] is None
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": 256}


# --------------------------------------------------------------------------
# Refusal (stop_reason == "refusal") falls back to the profile's fallback
# --------------------------------------------------------------------------

def _with_fallback(monkeypatch, manager, primary_responses, fallback_responses):
    primary = Hop(profile={"name": "atlas-haiku", "model": "claude-haiku-5-5"}, endpoint={"preset": "anthropic"})
    fallback = Hop(profile={"name": "minimax-fast", "model": "minimax-m2.7-highspeed"},
                   endpoint={"preset": "minimax"})
    resolution = SimpleNamespace(primary=primary, hops=[primary, fallback], is_fallback=lambda h: h is fallback)
    monkeypatch.setattr(QAManagerAgent, "_resolution", lambda self: resolution)
    stubs = {"primary": StubClient(primary_responses), "fallback": StubClient(fallback_responses)}
    monkeypatch.setattr(QAManagerAgent, "client", property(lambda self: stubs["primary"]))
    monkeypatch.setattr(QAManagerAgent, "_hop_client", lambda self, hop: stubs["fallback"])
    return stubs


def test_refusal_falls_back_to_next_profile(make_manager, monkeypatch):
    manager, _stub, _session = make_manager([])
    answer = Resp([text_b("ok from fallback")])
    stubs = _with_fallback(monkeypatch, manager, [Resp([], stop="refusal")], [answer])
    assert manager._create_turn({"max_tokens": 10}) is answer
    assert stubs["fallback"].messages.requests[0]["model"] == "minimax-m2.7-highspeed"


def test_refusal_on_every_profile_returns_the_refusal(make_manager, monkeypatch):
    manager, _stub, _session = make_manager([])
    refused = Resp([], stop="refusal")
    _with_fallback(monkeypatch, manager, [refused], [Resp([], stop="refusal")])
    assert manager._create_turn({"max_tokens": 10}) is refused
