"""TASK-114 P0-3b — planner-observation parsing and dry-run guard.

The model is faked here; the live run happens where the routing credentials are.
"""
from types import SimpleNamespace

import pytest

import scripts.bench_atlas_planner as planner
from agent.core.manager import QAManagerAgent
from agent.core.tool_bridge import ToolBridge


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Resp:
    def __init__(self, blocks, tin=7, tout=3):
        self.content = blocks
        self.usage = SimpleNamespace(input_tokens=tin, output_tokens=tout)


def test_parse_load_skill():
    d = planner.parse_response(Resp([Block(type="text", text="LOAD SKILL [device-control]")]))
    assert d["kind"] == "load_skill" and d["skill"] == "device-control"


def test_parse_direct_tool():
    d = planner.parse_response(Resp([Block(type="tool_use", name="get_device_info",
                                           input={"device_id": "TV-1"})]))
    assert d["kind"] == "direct_tool" and d["tool"] == "get_device_info"
    assert d["parameters"] == {"device_id": "TV-1"}


def test_parse_clarify_reject_text():
    assert planner.parse_response(Resp([Block(type="text", text="Which device do you mean?")]))["kind"] == "clarify"
    assert planner.parse_response(Resp([Block(type="text", text="I cannot do that")]))["kind"] == "reject"
    assert planner.parse_response(Resp([Block(type="text", text="done")]))["kind"] == "text"


def test_parse_refusal_that_asks_which_one_is_clarify():
    d = planner.parse_response(Resp([Block(
        type="text", text="I can't delete a test case without knowing which one you're referring to.")]))
    assert d["kind"] == "clarify"


def test_parse_policy_refusal_is_reject():
    d = planner.parse_response(Resp([Block(
        type="text", text="I can't do that: wiping a production database is destructive.")]))
    assert d["kind"] == "reject"


def test_run_never_executes_and_records_the_decision(monkeypatch):
    cases = [{"id": "T1", "prompt": "check whether device TV-1 is online", "category": "direct_mcp",
              "expected_skill": "device-control", "expected_mcp_tool": "get_device_info",
              "expected_action": "route"}]
    agent = QAManagerAgent(user_identifier="bench-team", agent_id="assistant")
    monkeypatch.setattr(agent, "_create_turn", lambda kwargs: Resp(
        [Block(type="tool_use", name="get_device_info", input={"device_id": "TV-1"})]))
    # no routing DB in the local test
    monkeypatch.setattr(QAManagerAgent, "_resolution", lambda self: (_ for _ in ()).throw(RuntimeError("no db")))
    monkeypatch.setattr(ToolBridge, "execute", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("tool executed")))

    rows, metrics = planner.run(cases, agent=agent, schemas={
        "get_device_info": {"input_schema": {"properties": {"device_id": {}}, "required": []}}})

    assert metrics["real_executions"] == 0
    assert metrics["mocked_dispatches"] == 1
    assert metrics["validated_dispatches"] == 1
    assert rows[0]["decision"]["kind"] == "direct_tool"
    assert rows[0]["dispatch"]["tool"] == "get_device_info"
    assert rows[0]["dispatch"]["executed"] is False
    assert rows[0]["tokens_in"] == 7


def test_router_prompt_includes_the_refusal_rule():
    m = QAManagerAgent(user_identifier="bench-team", agent_id="assistant")
    with_tools = m._build_router_prompt({}, "read another team's results", ["read_doc", "search_docs"])
    without_tools = m._build_router_prompt({}, "read another team's results", [])
    assert "I can't do that:" in with_tools
    assert "I can't do that:" in without_tools


def test_dev_safety_set_loads_and_has_both_labels():
    rows = planner.load_jsonl("tests/benchmarks/atlas_dev_safety_2026-10-17.jsonl")
    assert len(rows) == 20
    assert sum(1 for r in rows if r["expected_action"] == "reject") == 16
    assert sum(1 for r in rows if r["expected_action"] == "clarify") == 4


def test_run_records_a_load_skill_decision(monkeypatch):
    cases = [{"id": "T2", "prompt": "show the current system health", "category": "direct_skill",
              "expected_skill": "check-system-health", "expected_mcp_tool": "get_device_info",
              "expected_action": "route"}]
    agent = QAManagerAgent(user_identifier="bench-team", agent_id="assistant")
    monkeypatch.setattr(agent, "_create_turn", lambda kwargs: Resp(
        [Block(type="text", text="LOAD SKILL [check-system-health]")]))
    monkeypatch.setattr(QAManagerAgent, "_resolution", lambda self: (_ for _ in ()).throw(RuntimeError("no db")))
    rows, metrics = planner.run(cases, agent=agent, schemas={})
    assert rows[0]["decision"]["kind"] == "load_skill"
    assert rows[0]["decision"]["skill"] == "check-system-health"
    assert metrics["mocked_dispatches"] == 0
