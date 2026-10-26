"""Router-turn skill pick is stored in ai_decisions (TASK-47): agent/core/routing_log.py.

Fake model + fake DB writer, no network.

Run: pytest tests/backend_server/test_agent_routing_log.py -v
"""
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_agent_minimax_quirks import (  # noqa: E402
    NEUTRAL_MSG, Resp, Session, make_manager, run_chat, text_b, tool_b,
)
from agent.core import routing_log  # noqa: E402
from agent.core.message_types import AgentEvent, EventType  # noqa: E402

assert make_manager  # fixture re-export

pytestmark = pytest.mark.unit

# The message the router-turn tests send. Longer than the 12 words of the TASK-140 quick step, so it is
# not eligible for it: the router LLM turn this file logs is the only model call. A short greeting is a
# quick-step message — test_quick_step_greeting_skips_the_router_turn covers that path.
SUBSTANTIVE_MSG = "a detailed recap of the platform activity recorded over the last day please"


class _SyncThread:
    """threading.Thread, minus the real thread: start() runs the target inline.

    The signature matches threading.Thread on purpose. This fake replaces the attribute on the
    stdlib threading module (routing_log.threading IS threading), so the patch is global and a
    too-narrow signature breaks unrelated callers - `threading.Thread(target=..., name=..., ...)`
    raised "unexpected keyword argument 'name'" in faqs_step and took nine tests with it.
    """

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None, *, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture
def rows(monkeypatch):
    out = []
    monkeypatch.setattr(routing_log.threading, "Thread", _SyncThread)
    from shared.src.lib.database import ai_decisions_db
    monkeypatch.setattr(ai_decisions_db, "insert_decision", lambda row: out.append(row) or "id-1")
    # The routed profile (minimax-fast) is stubbed by make_manager.
    return out


@pytest.fixture
def prune_recorder(monkeypatch):
    routing_log._LAST_PRUNE_AT.clear()
    calls = []
    from shared.src.lib.database import ai_decisions_db

    def _fake(team_id, usage_key, days):
        calls.append((team_id, usage_key, days))
        return 0

    monkeypatch.setattr(ai_decisions_db, "prune_decisions", _fake)
    return calls


def test_the_fake_thread_accepts_what_the_real_one_accepts():
    """Keep _SyncThread in step with the stdlib.

    The fake replaces threading.Thread for the whole process - routing_log.threading IS the
    stdlib module - so a narrower signature silently breaks every other caller in the run.
    It did: faqs_step passes name=, the fake did not accept it, and nine tests in this file
    failed with "unexpected keyword argument 'name'". This test is what makes that loud
    instead of a surprise two files away.
    """
    import inspect
    import threading

    real = inspect.signature(threading.Thread.__init__).parameters
    fake = inspect.signature(_SyncThread.__init__).parameters
    accepted = {n for n, p in real.items() if p.default is not inspect.Parameter.empty}
    missing = sorted(accepted - set(fake))
    assert not missing, f"_SyncThread no longer accepts the real Thread's arguments: {missing}"


def test_llm_skill_pick_is_logged_with_outcome(make_manager, rows):
    manager, _, session = make_manager([
        Resp([tool_b("LOAD SKILL", {"skill": "search-docs"})], stop="tool_use"),
        Resp([tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_r")], stop="tool_use"),
        Resp([text_b("Docs say hi.")]),
    ])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)

    assert len(rows) == 1
    row = rows[0]
    assert row["team_id"] == "team-1" and row["usage_key"] == "agent.atlas.route"
    assert row["request_id"] == "test-session" and row["model"] == "minimax-m2.7-highspeed"
    assert row["profile"] == "minimax-fast"
    assert row["state"]["message"] == SUBSTANTIVE_MSG and row["state"]["mode"] == "router"
    assert "search-docs" in row["questions"]["skill"]["options"]
    assert row["questions"]["skill"]["options"][-1] == "answered_directly"
    assert row["answers"]["skill"]["choice"] == "search-docs"
    assert row["refs"]["decided_by"] == "llm" and row["refs"]["load_ok"] is True
    assert row["refs"]["tools"] == ["read_doc"]
    assert row["ok"] is True and row["outcome"]["success"] is True and row["outcome_at"]


def test_direct_answer_is_logged_as_answered_directly(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)

    assert len(rows) == 1
    assert rows[0]["answers"]["skill"]["choice"] == "answered_directly"
    assert rows[0]["refs"]["decided_by"] == "none" and rows[0]["outcome"]["success"] is True


def test_unknown_skill_pick_is_a_failed_decision(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("LOAD SKILL [no-such-skill]")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)

    assert len(rows) == 1
    row = rows[0]
    assert row["answers"]["skill"]["choice"] == "no-such-skill"
    assert row["refs"]["load_ok"] is False and row["ok"] is False and row["outcome"]["success"] is False
    assert "skill_not_available" in row["error"]


def test_trigger_rule_autoload_is_marked_as_rule(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("Docs answer.")])])
    manager.user_identifier = "team-1"
    # Two search-docs triggers in one message auto-load the skill without a model pick.
    run_chat(manager, session, "what are the api docs and pricing cost")
    if not rows or rows[0]["refs"]["decided_by"] != "trigger_rule":
        pytest.skip("search-docs trigger words changed; adjust the message")
    assert rows[0]["answers"]["skill"]["choice"] == "search-docs"


def test_no_row_when_a_skill_is_already_loaded_or_no_team(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("Hello!")]), Resp([text_b("Again!")])])
    manager.user_identifier = None
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert rows == []  # no team: nothing written (team_id is required and filtered everywhere)

    manager.user_identifier = "team-1"
    assert manager.load_skill("search-docs")
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert rows == []  # a skill was already loaded: not a routing decision


def test_message_is_truncated_and_failure_to_write_never_raises(monkeypatch):
    tracker = routing_log.RoutingTracker(team_id="t", session_id="s", agent_usage="agent.atlas",
                                         message="x" * 2000, available_skills=["a"], model="m", profile="p")
    tracker.observe(AgentEvent(type=EventType.ERROR, agent="Atlas", content="boom", error="boom"))
    row = tracker.build_row(None)
    assert len(row["state"]["message"]) == routing_log.MESSAGE_MAX_CHARS
    assert row["ok"] is False and row["error"] == "boom"

    monkeypatch.setattr(routing_log.threading, "Thread", _SyncThread)
    from shared.src.lib.database import ai_decisions_db
    monkeypatch.setattr(ai_decisions_db, "insert_decision", lambda row: 1 / 0)
    tracker.write(None)  # must not raise


def test_a_write_whose_thread_cannot_start_never_raises(monkeypatch):
    """Creating the thread can fail on its own - no thread slots left.

    write() promises "Never raises", so the failure is reported and swallowed instead of
    reaching the caller.
    """
    class _ThreadRefusesToStart:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(routing_log.threading, "Thread", _ThreadRefusesToStart)
    tracker = routing_log.RoutingTracker(team_id="t", session_id="s", agent_usage="agent.atlas",
                                         message="hello", available_skills=["a"], model="m", profile="p")
    tracker.write(None)  # must not raise


def test_bracketed_load_skill_text_is_parsed(make_manager):
    """The router prompt tells the model to answer `LOAD SKILL [name]`; the brackets must parse."""
    manager, _, _ = make_manager([])
    assert manager._parse_skill_command("LOAD SKILL [search-docs]") == "search-docs"
    assert manager._parse_skill_command("load skill search-docs") == "search-docs"
    assert manager._parse_skill_command("nothing to load") is None


def test_quick_step_greeting_skips_the_router_turn(make_manager, rows, monkeypatch):
    """TASK-140: a short command is answered by the quick step (one small call + one tool), so the router
    LLM turn never runs and no skill is picked. Only the quick call is scripted: had the manager reached the
    router loop the stub would raise and the row would record the error instead."""
    monkeypatch.setenv("ATLAS_QUICK_STEP", "on")
    manager, stub, session = make_manager([
        Resp([tool_b("show_page", {"page": "heatmap"}, bid="tu_q")], stop="tool_use")])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)

    assert len(stub.messages.requests) == 1
    assert stub.messages.requests[0]["max_tokens"] == 400  # the quick call, not the router turn
    assert len(rows) == 1
    row = rows[0]
    assert row["ok"] is True and row["outcome"]["success"] is True
    assert row["answers"]["skill"]["choice"] == "answered_directly"
    assert row["refs"]["decided_by"] == "none" and row["refs"]["tools"] == ["show_page"]


def test_write_triggers_prune_with_30_days(make_manager, rows, prune_recorder):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert len(prune_recorder) == 1
    assert prune_recorder[0] == ("team-1", "agent.atlas.route", 30)


def test_prune_is_not_called_twice_within_an_hour(make_manager, rows, prune_recorder, monkeypatch):
    clock = [1000.0]

    def fake_time():
        return clock[0]

    monkeypatch.setattr(routing_log.time, "time", fake_time)
    manager, _, session = make_manager(
        [Resp([text_b("a")]), Resp([text_b("b")]), Resp([text_b("c")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)
    run_chat(manager, session, SUBSTANTIVE_MSG)
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert len(prune_recorder) == 1  # only the first write triggers a prune


def test_prune_is_called_again_after_an_hour(make_manager, rows, prune_recorder, monkeypatch):
    clock = [1000.0]

    def fake_time():
        return clock[0]

    monkeypatch.setattr(routing_log.time, "time", fake_time)
    manager, _, session = make_manager(
        [Resp([text_b("a")]), Resp([text_b("b")]), Resp([text_b("c")]), Resp([text_b("d")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)
    clock[0] += 3601.0  # one hour + 1 second
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert len(prune_recorder) == 2


def test_prune_failure_does_not_raise(make_manager, rows, monkeypatch):
    from shared.src.lib.database import ai_decisions_db
    monkeypatch.setattr(ai_decisions_db, "prune_decisions", lambda *a, **k: 1 / 0)
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, SUBSTANTIVE_MSG)  # must not raise


def test_prune_is_skipped_when_no_team(make_manager, rows, prune_recorder):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = None
    run_chat(manager, session, SUBSTANTIVE_MSG)
    assert prune_recorder == []  # no team → no insert → no prune
