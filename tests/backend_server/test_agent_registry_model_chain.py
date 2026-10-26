"""
Agent Registry model-chain shape (backend_server/src/routes/agent_registry_routes.py).

The Atlas UI model picker reads `model_chain` (primary + fallbacks) from the agent
listing endpoint. This is a unit test: a hand-built AgentDefinition + a faked AI
routing snapshot — no live server, no DB.

Guard: protects against the chain silently collapsing to a single hop, the role
flags regressing, or the chain being empty when a route exists.
"""
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))
sys.path.insert(0, str(REPO / "shared" / "lib"))

try:
    from agent.registry import AgentDefinition  # noqa: E402
    from backend_server.src.routes.agent_registry_routes import (  # noqa: E402
        _agent_to_dict_with_model,
        _resolve_agent_chain,
    )
    from shared.src.lib.ai import router as ai_router  # noqa: E402
    from shared.src.lib.database import ai_routing_db  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"deps not installed: {exc}", allow_module_level=True)


pytestmark = pytest.mark.unit  # bypass tests/backend_server/conftest.py:server probe


def _build_agent(agent_id: str = "atlas") -> AgentDefinition:
    """A minimal Atlas agent. Only `metadata.id` is read by _resolve_agent_chain.",
    """
    return AgentDefinition(
        metadata={
            "id": agent_id,
            "name": agent_id,
            "nickname": agent_id.capitalize(),
            "description": "",
            "selectable": True,
            "version": "1.0.0",
            "author": "test",
            "tags": [],
            "suggestions": [],
            "prompt_presets": [],
        },
        triggers=[],
        event_pools=[],
        subagents=[],
        available_skills=[],
        skills=[],
        permissions={"actions": {}, "control": {}},
        config={"platform_filter": "all"},
    )


def _install_routing(monkeypatch, primary_id="p-primary", fallback_id="p-fallback"):
    """Install a one-route snapshot with one primary + one fallback profile.",
    """
    snapshot = {
        "endpoints": {"e-cloud": {"id": "e-cloud", "name": "openrouter",
                                  "preset": "openrouter", "enabled": True,
                                  "allowed_team_ids": []}},
        "profiles": {
            primary_id: {"id": primary_id, "name": "primary-claude",
                         "endpoint_id": "e-cloud", "model": "openai/gpt-5",
                         "fallback_profile_id": fallback_id, "enabled": True,
                         "capabilities": ["text"]},
            fallback_id: {"id": fallback_id, "name": "fallback-minimax",
                          "endpoint_id": "e-cloud", "model": "minimax-m3",
                          "enabled": True, "capabilities": ["text"]},
        },
        "routes": [{"id": "r-agent", "usage_key": "agent.atlas",
                    "team_id": None, "profile_id": primary_id,
                    "enabled": True, "priority": 100}],
    }
    # The registry route calls ai_router.resolve(...).primary.model — and now also
    # ai_router.resolve(...) for the chain. set_snapshot_for_tests is the public hook.
    ai_router.set_snapshot_for_tests(snapshot)
    monkeypatch.setattr(ai_router, "CACHE_TTL_S", 10 ** 9)
    # The DB is touched when the registry adds an enabled check on the fallback;
    # stub it so a missing DB never makes the test red.
    monkeypatch.setattr(ai_routing_db, "get_row", lambda *a, **k: None)


def _teardown():
    ai_router.set_snapshot_for_tests(None)


@pytest.fixture
def routing(monkeypatch):
    _install_routing(monkeypatch)
    yield
    _teardown()


def test_resolve_chain_returns_primary_then_fallback(routing):
    chain = _resolve_agent_chain("atlas")
    assert [hop["role"] for hop in chain] == ["primary", "fallback"]
    assert [hop["fallback_index"] for hop in chain] == [0, 1]
    assert [hop["profile_name"] for hop in chain] == ["primary-claude", "fallback-minimax"]
    assert chain[0]["model"] == "openai/gpt-5"
    assert chain[1]["model"] == "minimax-m3"


def test_resolve_chain_includes_endpoint_metadata(routing):
    chain = _resolve_agent_chain("atlas")
    for hop in chain:
        assert hop["endpoint_name"] == "openrouter"
        assert hop["preset"] == "openrouter"
        # profile_id is required: the picker posts it back as `pinned_profile_id`
        # and the server validates it against ai_routing_db.
        assert hop["profile_id"] in {"p-primary", "p-fallback"}


def test_resolve_chain_empty_when_no_route(routing, monkeypatch):
    """Empty routing snapshot — the picker gracefully shows an empty dropdown
    instead of crashing the agent list page."
    """
    ai_router.set_snapshot_for_tests({
        "endpoints": {}, "profiles": {}, "routes": [],
    })
    assert _resolve_agent_chain("atlas") == []


def test_agent_dict_exposes_chain_and_primary_model(routing):
    agent = _build_agent("atlas")
    data = _agent_to_dict_with_model(agent)
    # `model` stays the primary's model (back-compat with the existing UI label).
    assert data["model"] == "openai/gpt-5"
    assert isinstance(data["model_chain"], list)
    assert len(data["model_chain"]) == 2
    assert data["model_chain"][0]["role"] == "primary"
    assert data["model_chain"][1]["role"] == "fallback"