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
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))
sys.path.insert(0, str(REPO / "shared" / "lib"))

os.environ.setdefault("AI_AGENT_PROVIDER", "minimax")
os.environ.setdefault("MINIMAX_API_KEY", "test-key-not-used")

# The agent stack pulls in the server's runtime deps (anthropic, redis, langfuse, …). CI's
# backend job installs only pytest/requests, so skip this module there instead of aborting
# the whole collection ("1 error during collection" took every other test down with it).
try:
    from agent.core.manager import QAManagerAgent  # noqa: E402
    from agent.core.message_types import EventType  # noqa: E402
    from agent.core.session import Session  # noqa: E402
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
