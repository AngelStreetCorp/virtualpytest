"""
Atlas model picker — per-session pin (backend_server/src/agent/core/manager.py:
_resolution honours session.context['pinned_profile_id']).

When the user picks a profile from the agent's model chain (Atlas UI fallback
dropdown), the next turn must use ONLY that profile — fallbacks are skipped.
The pin is per-session: clearing it (empty string) reverts to the default chain.

Pure unit test: no LLM calls, no DB. The shared AI router snapshot is installed
in-memory so `ai_router.resolve_profile` returns a one-hop Resolution.
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "backend_server" / "src"))
sys.path.insert(0, str(REPO / "shared" / "lib"))

try:
    from agent.core.manager import QAManagerAgent  # noqa: E402
    from agent.core.session import Session  # noqa: E402
    from shared.src.lib.ai import router as ai_router  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)


pytestmark = pytest.mark.unit  # bypass tests/backend_server/conftest.py:server probe


PROFILES = [
    {"id": "p-primary", "name": "primary-claude", "model": "openai/gpt-5",
     "endpoint_id": "e-cloud", "fallback_profile_id": "p-fallback",
     "enabled": True, "capabilities": ["text"]},
    {"id": "p-fallback", "name": "fallback-minimax", "model": "minimax-m3",
     "endpoint_id": "e-cloud", "enabled": True, "capabilities": ["text"]},
]
ENDPOINTS = {"e-cloud": {"id": "e-cloud", "name": "openrouter", "preset": "openrouter",
                         "enabled": True, "allowed_team_ids": []}}
ROUTES = [{"id": "r-agent", "usage_key": "agent.atlas", "team_id": None,
           "profile_id": "p-primary", "enabled": True, "priority": 100}]


def _install(monkeypatch):
    ai_router.set_snapshot_for_tests({
        "endpoints": ENDPOINTS,
        "profiles": {p["id"]: p for p in PROFILES},
        "routes": ROUTES,
    })
    monkeypatch.setattr(ai_router, "CACHE_TTL_S", 10 ** 9)


def _teardown():
    ai_router.set_snapshot_for_tests(None)


@pytest.fixture
def manager(monkeypatch):
    _install(monkeypatch)
    session = Session(id="test-session")
    yield QAManagerAgent(user_identifier="team-test", session=session)
    _teardown()


def test_default_resolution_returns_full_chain(manager):
    """Without a pin, the chain is the route's primary + fallback (TASK-30)."""
    resolution = manager._resolution()
    assert [h.profile_name for h in resolution.hops] == ["primary-claude", "fallback-minimax"]


def test_pinned_resolution_returns_single_hop(manager):
    """Pin to the fallback profile: only that hop, no chain."""
    manager._session.set_context("pinned_profile_id", "p-fallback")
    resolution = manager._resolution()
    assert [h.profile_name for h in resolution.hops] == ["fallback-minimax"]
    assert resolution.layer == "pinned"
    assert resolution.via_key == "profile:fallback-minimax"


def test_pinned_primary_also_returns_single_hop(manager):
    """Pinning the primary is legal: still one hop, the chain's primary only."""
    manager._session.set_context("pinned_profile_id", "p-primary")
    resolution = manager._resolution()
    assert [h.profile_name for h in resolution.hops] == ["primary-claude"]


def test_clearing_pin_reverts_to_chain(manager):
    """Empty / missing pin restores the default chain."""
    manager._session.set_context("pinned_profile_id", "p-fallback")
    assert [h.profile_name for h in manager._resolution().hops] == ["fallback-minimax"]
    manager._session.set_context("pinned_profile_id", "")
    assert [h.profile_name for h in manager._resolution().hops] == ["primary-claude", "fallback-minimax"]


def test_stale_pin_falls_back_to_chain(manager):
    """If the pinned profile was removed/disabled since the user picked it, do not
    crash the turn — fall back to the default chain (manager is fault-tolerant)."""
    manager._session.set_context("pinned_profile_id", "p-deleted")
    resolution = manager._resolution()
    # Default chain still works; the stale id is silently ignored.
    assert [h.profile_name for h in resolution.hops] == ["primary-claude", "fallback-minimax"]


def test_pinned_profile_marks_itself_as_not_fallback(manager):
    """When pinned, Resolution.is_fallback(hop) must be False — stats/traces still
    tag the call as primary (TASK-30 contract: pinned = single hop, no fallback)."""
    manager._session.set_context("pinned_profile_id", "p-fallback")
    resolution = manager._resolution()
    assert resolution.is_fallback(resolution.primary) is False