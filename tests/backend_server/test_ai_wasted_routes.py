"""BUG-0514: /resolve reports a paused route unavailable; a Settings test makes no request while paused."""
import os
import sys
import time

import pytest
from flask import Flask

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend_server", "src"))

from backend_server.src.routes import server_ai_routing_routes as routes  # noqa: E402
from shared.src.lib.ai import router  # noqa: E402
from tests.shared import ai_routing_fixtures as fx  # noqa: E402


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def setup(monkeypatch):
    fx.install_routing(monkeypatch)
    monkeypatch.setattr(router, "credit_available", lambda hop: False)
    yield
    fx.clear_routing()


def test_resolve_says_unavailable_while_every_hop_is_paused(setup):
    with Flask("t").test_request_context("/server/ai/resolve", method="POST", json={"usage": "agent.browser"}):
        assert _unwrap(routes.resolve)().get_json()["available"] is True
    router._no_credit[fx.ENDPOINT_ID] = (time.time() + 600, 600)
    with Flask("t").test_request_context("/server/ai/resolve", method="POST", json={"usage": "agent.browser"}):
        body = _unwrap(routes.resolve)().get_json()
    assert body["available"] is False and "no credit" in body["paused"]


def test_settings_test_makes_no_request_while_the_endpoint_is_paused(setup, monkeypatch):
    recorded = []
    monkeypatch.setattr(router, "record", lambda *a, **k: recorded.append(k))
    router._no_credit[fx.ENDPOINT_ID] = (time.time() + 600, 600)
    hop = router.resolve("agent.browser").primary
    sent = []
    with pytest.raises(RuntimeError, match="no credit"):
        routes._counted_test(hop, "chat", lambda: sent.append(1))
    assert sent == [] and recorded[0]["outcome"] == "skipped"
