"""BUG-0510/0507: the OpenAI passthrough honours the no-credit pause and attributes unnamed clients."""
import os
import sys
import time

import pytest
from flask import Flask

pytestmark = pytest.mark.unit

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)
sys.path.insert(0, os.path.join(_repo_root, "backend_server", "src"))

from backend_server.src.routes import server_ai_routing_routes as routes  # noqa: E402
from shared.src.lib.ai import caller, router  # noqa: E402
from tests.shared import ai_routing_fixtures as fx  # noqa: E402


def _unwrap(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def setup(monkeypatch):
    fx.install_routing(monkeypatch)
    recorded = []
    monkeypatch.setattr(router, "record", lambda *a, **k: recorded.append(k))
    posts = []
    monkeypatch.setattr(routes.requests, "post", lambda *a, **k: posts.append(a) or (_ for _ in ()).throw(AssertionError("no provider call")))
    monkeypatch.setattr(routes.tracing, "trace_call", lambda **k: None)
    monkeypatch.setattr(caller, "_env_loaded", True)
    caller.clear()
    yield recorded, posts
    caller.clear()
    fx.clear_routing()


def _call(headers=None):
    app = Flask("t")
    with app.test_request_context("/server/ai/openai/agent.browser/chat/completions", method="POST",
                                  json={"messages": []}, headers=headers or {}, environ_base={"REMOTE_ADDR": "10.0.0.9"}):
        response = _unwrap(routes.openai_passthrough)("agent.browser")
        return response, caller.current()


def test_paused_endpoint_answers_402_locally_and_counts_one_skipped_call(setup):
    recorded, posts = setup
    router._no_credit[fx.ENDPOINT_ID] = (time.time() + 600, 600)
    response, _ = _call()
    status = response.status_code if hasattr(response, "status_code") else response[1]
    assert status == 402
    assert posts == []
    assert len(recorded) == 1
    assert recorded[0]["outcome"] == "skipped" and recorded[0]["error_type"] == "no_credit"


def test_a_client_naming_nobody_gets_a_stable_client_hash(setup):
    router._no_credit[fx.ENDPOINT_ID] = (time.time() + 600, 600)
    _, first = _call({"User-Agent": "curl/8"})
    caller.clear()
    _, again = _call({"User-Agent": "curl/8"})
    caller.clear()
    _, other = _call({"User-Agent": "other"})
    assert first["client_hash"] == again["client_hash"] != other["client_hash"]


def test_a_named_caller_gets_no_client_hash(setup):
    router._no_credit[fx.ENDPOINT_ID] = (time.time() + 600, 600)
    caller.bind(origin="script", host_name="h1")
    _, fields = _call()
    assert "client_hash" not in fields
