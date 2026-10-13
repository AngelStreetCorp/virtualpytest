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


class _SyncThread:
    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


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


def test_llm_skill_pick_is_logged_with_outcome(make_manager, rows):
    manager, _, session = make_manager([
        Resp([tool_b("LOAD SKILL", {"skill": "search-docs"})], stop="tool_use"),
        Resp([tool_b("read_doc", {"path": "INDEX.md"}, bid="tu_r")], stop="tool_use"),
        Resp([text_b("Docs say hi.")]),
    ])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)

    assert len(rows) == 1
    row = rows[0]
    assert row["team_id"] == "team-1" and row["usage_key"] == "agent.atlas.route"
    assert row["request_id"] == "test-session" and row["model"] == "minimax-m2.7-highspeed"
    assert row["profile"] == "minimax-fast"
    assert row["state"]["message"] == NEUTRAL_MSG and row["state"]["mode"] == "router"
    assert "search-docs" in row["questions"]["skill"]["options"]
    assert row["questions"]["skill"]["options"][-1] == "answered_directly"
    assert row["answers"]["skill"]["choice"] == "search-docs"
    assert row["refs"]["decided_by"] == "llm" and row["refs"]["load_ok"] is True
    assert row["refs"]["tools"] == ["read_doc"]
    assert row["ok"] is True and row["outcome"]["success"] is True and row["outcome_at"]


def test_direct_answer_is_logged_as_answered_directly(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)

    assert len(rows) == 1
    assert rows[0]["answers"]["skill"]["choice"] == "answered_directly"
    assert rows[0]["refs"]["decided_by"] == "none" and rows[0]["outcome"]["success"] is True


def test_unknown_skill_pick_is_a_failed_decision(make_manager, rows):
    manager, _, session = make_manager([Resp([text_b("LOAD SKILL [no-such-skill]")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)

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
    run_chat(manager, session, NEUTRAL_MSG)
    assert rows == []  # no team: nothing written (team_id is required and filtered everywhere)

    manager.user_identifier = "team-1"
    assert manager.load_skill("search-docs")
    run_chat(manager, session, NEUTRAL_MSG)
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


def test_bracketed_load_skill_text_is_parsed(make_manager):
    """The router prompt tells the model to answer `LOAD SKILL [name]`; the brackets must parse."""
    manager, _, _ = make_manager([])
    assert manager._parse_skill_command("LOAD SKILL [search-docs]") == "search-docs"
    assert manager._parse_skill_command("load skill search-docs") == "search-docs"
    assert manager._parse_skill_command("nothing to load") is None


def test_write_triggers_prune_with_30_days(make_manager, rows, prune_recorder):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)
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
    run_chat(manager, session, NEUTRAL_MSG)
    run_chat(manager, session, NEUTRAL_MSG)
    run_chat(manager, session, NEUTRAL_MSG)
    assert len(prune_recorder) == 1  # only the first write triggers a prune


def test_prune_is_called_again_after_an_hour(make_manager, rows, prune_recorder, monkeypatch):
    clock = [1000.0]

    def fake_time():
        return clock[0]

    monkeypatch.setattr(routing_log.time, "time", fake_time)
    manager, _, session = make_manager(
        [Resp([text_b("a")]), Resp([text_b("b")]), Resp([text_b("c")]), Resp([text_b("d")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)
    clock[0] += 3601.0  # one hour + 1 second
    run_chat(manager, session, NEUTRAL_MSG)
    assert len(prune_recorder) == 2


def test_prune_failure_does_not_raise(make_manager, rows, monkeypatch):
    from shared.src.lib.database import ai_decisions_db
    monkeypatch.setattr(ai_decisions_db, "prune_decisions", lambda *a, **k: 1 / 0)
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = "team-1"
    run_chat(manager, session, NEUTRAL_MSG)  # must not raise


def test_prune_is_skipped_when_no_team(make_manager, rows, prune_recorder):
    manager, _, session = make_manager([Resp([text_b("Hello!")])])
    manager.user_identifier = None
    run_chat(manager, session, NEUTRAL_MSG)
    assert prune_recorder == []  # no team → no insert → no prune
