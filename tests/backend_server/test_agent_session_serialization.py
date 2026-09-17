"""Session.to_dict() must survive whatever an agent parked in `context`.

BUG-0129: ToolBridge stores a live ToolResultCache in `session.context['_tool_result_cache']`,
and to_dict() handed `context` straight to jsonify — so GET /server/agent/sessions answered
500 "Object of type ToolResultCache is not JSON serializable" as soon as any in-memory session
had run a tool. Intermittent by nature (it depends on what is in memory), which is why it
passed CI run 705 and failed 708.

The real ToolResultCache is NOT imported here: `agent.core.tool_bridge` pulls in
flask_socketio, which the CI backend job does not install, and an ImportError at collection
takes the whole suite down with it (that is exactly what happened to this file in run 714).
`agent.core.session` itself only needs the stdlib. What the fix has to hold is "a live object
in context does not break the listing", and any unserializable object proves that.

Run: pytest tests/backend_server/test_agent_session_serialization.py -v   (no server needed)
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend_server" / "src"))

from agent.core.session import Session  # noqa: E402

pytestmark = pytest.mark.unit


class LiveToolCache:
    """Stands in for ToolResultCache: an object json.dumps refuses, held in session context."""

    def __init__(self):
        self._cache = {"call-1": {"result": "screenshot.png"}}


def _session_with_tool_cache() -> Session:
    session = Session(id="unit-test-session")
    session.set_context("userinterface_name", "virtualpytest_web")
    session.context["_tool_result_cache"] = LiveToolCache()
    return session


def test_to_dict_is_json_serializable_with_a_live_tool_cache():
    json.dumps(_session_with_tool_cache().to_dict())


def test_internal_context_keys_are_not_exposed():
    body = _session_with_tool_cache().to_dict()
    assert "_tool_result_cache" not in body["context"]
    assert body["context"]["userinterface_name"] == "virtualpytest_web"


def test_an_unserializable_public_value_is_dropped_not_fatal():
    """One bad value must not take the whole session listing down with it."""
    session = Session(id="unit-test-session")
    session.set_context("keep_me", {"nested": [1, 2, 3]})
    session.set_context("device_controller", LiveToolCache())
    body = session.to_dict()
    json.dumps(body)
    assert body["context"]["keep_me"] == {"nested": [1, 2, 3]}
    assert "device_controller" not in body["context"]
