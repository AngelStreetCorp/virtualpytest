"""BUG-0514: a browser-use task makes no model request while agent.browser has no credit, and stops at the first 402."""
import asyncio
import os
import sys
import types

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)


@pytest.fixture
def utils(monkeypatch):
    stub = types.ModuleType("browser_use")
    stub.Agent = object
    llm = types.ModuleType("browser_use.llm")
    llm.ChatOpenAI = object
    monkeypatch.setitem(sys.modules, "browser_use", stub)
    monkeypatch.setitem(sys.modules, "browser_use.llm", llm)
    sys.modules.pop("backend_host.src.lib.utils.browseruse_utils", None)
    from backend_host.src.lib.utils import browseruse_utils
    return browseruse_utils


def test_task_is_refused_before_any_request_when_the_route_is_paused(utils, monkeypatch):
    from shared.src.lib.ai import gateway
    monkeypatch.setattr(gateway, "is_available", lambda usage, team_id=None, context=None: False)
    with pytest.raises(utils.ModelUnavailable):
        asyncio.run(utils.BrowserUseManager(None).execute_task("x"))


def test_first_402_stops_the_agent(utils):
    stopped, stop = [], {}
    stop["agent"] = types.SimpleNamespace(stop=lambda: stopped.append(1))
    client = utils._stop_on_refusal_client(stop)
    hook = client.event_hooks["response"][0]
    asyncio.run(hook(types.SimpleNamespace(status_code=200)))
    assert stopped == [] and "reason" not in stop
    asyncio.run(hook(types.SimpleNamespace(status_code=402)))
    assert stopped == [1] and "402" in stop["reason"]
