"""A step with no KPI anchors must not pay for a before-action screenshot (TASK-161).

The frame captured "before the last action" exists for exactly one consumer: the KPI request the
navigation executor writes when the action set carries `kpi_references` or
`use_verifications_for_kpi`. On a web host the capture is a page screenshot that regularly times
out after 20 s — measured on `web-wikipedia`: every navigation of a two-pass smoke walk paid the
full 20 s and the frame was then discarded, which is ~11 minutes of a 24-minute run.

So `execute_actions` takes `capture_before_action_screenshot` (default True, so every existing
caller is unchanged) and the navigation loop passes `bool(_resolve_kpi_references(step))`.
"""
import asyncio
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


class _FakeWebController:
    """A web action only needs a controller whose send_command answers success."""

    def __init__(self):
        self.calls = []

    def send_command(self, command, **params):
        self.calls.append({"command": command, "params": dict(params)})
        return {"success": True, "url": params.get("url")}


class _FakeDevice:
    def __init__(self):
        self.host_name = "test-host"
        self.device_id = "host"
        self.device_model = "web"
        self.device_name = "host-test"
        self.navigation_context = {}
        self.get_capture_dir = lambda subfolder="": "/tmp"
        self.web = _FakeWebController()

    def _get_controller(self, name):
        return self.web if name == "web" else None


_CAPTURES = {"n": 0}


@pytest.fixture(autouse=True)
def _count_captures(monkeypatch):
    """Count the before-action captures without touching a real device or the filesystem."""
    _CAPTURES["n"] = 0
    import shared.src.lib.utils.device_utils as device_utils

    def fake_capture(device, context=None, *a, **kw):
        _CAPTURES["n"] += 1
        return "/tmp/before.jpg"

    monkeypatch.setattr(device_utils, "capture_screenshot", fake_capture)
    yield _CAPTURES


def _executor():
    from backend_host.src.services.actions.action_executor import ActionExecutor
    return ActionExecutor(_FakeDevice(), _from_device_init=True)


def _web_navigation():
    return {"command": "navigate_to_url", "action_type": "web",
            "params": {"url": "/wiki/Main_Page", "wait_time": 100}}


def test_no_capture_when_the_caller_says_no():
    """Asking not to capture removes exactly the before-action frame and nothing else.

    The per-action "after" screenshot is a different capture in the same helper, so the
    contract is one capture fewer than the default, not zero captures.
    """
    asyncio.run(_executor().execute_actions(actions=[_web_navigation()]))
    with_default = _CAPTURES["n"]
    assert with_default >= 1

    _CAPTURES["n"] = 0
    result = asyncio.run(_executor().execute_actions(
        actions=[_web_navigation()],
        capture_before_action_screenshot=False,
    ))
    assert result["before_action_screenshot"] == ""
    assert _CAPTURES["n"] == with_default - 1


def test_default_still_captures():
    """Every existing caller keeps today's behaviour: the capture happens unless asked not to."""
    result = asyncio.run(_executor().execute_actions(actions=[_web_navigation()]))
    assert result["before_action_screenshot"] == "/tmp/before.jpg"
    assert _CAPTURES["n"] >= 1          # the before frame plus the per-action after frame


def test_no_actions_means_no_capture_either_way():
    asyncio.run(_executor().execute_actions(actions=[], capture_before_action_screenshot=True))
    assert _CAPTURES["n"] == 0


def test_navigation_executor_only_asks_for_the_frame_when_kpi_is_queued():
    """The caller-side condition is what makes the saving safe: same list the KPI guard uses."""
    from backend_host.src.services.navigation.navigation_executor import NavigationExecutor

    step_without_kpi = {
        "to_node_id": "home",
        "action_set_id": "home_to_home_1",
        "original_edge_data": {"action_sets": [{"id": "home_to_home_1", "actions": []}]},
    }
    step_with_kpi = {
        "to_node_id": "home",
        "action_set_id": "home_to_home_1",
        "original_edge_data": {"action_sets": [{
            "id": "home_to_home_1", "actions": [],
            "kpi_references": [{"verification_type": "web", "command": "waitForElementToAppear"}],
        }]},
    }
    step_with_node_verifications = {
        "to_node_id": "home",
        "action_set_id": "home_to_home_1",
        "original_edge_data": {"action_sets": [{
            "id": "home_to_home_1", "actions": [], "use_verifications_for_kpi": True,
        }]},
    }

    executor = NavigationExecutor.__new__(NavigationExecutor)
    executor.unified_graph = None      # no populated graph: use_verifications_for_kpi finds nothing
    assert not executor._resolve_kpi_references(step_without_kpi)
    assert executor._resolve_kpi_references(step_with_kpi)
    # use_verifications_for_kpi reads the destination node's verifications, which the unified
    # graph puts on the step; with none present it resolves to no reference, which is the case
    # the navigation loop must treat as "no frame wanted".
    assert not executor._resolve_kpi_references(step_with_node_verifications)