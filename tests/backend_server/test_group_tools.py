"""MCP group tools (TASK-76): backend_server/src/mcp/tools/group_tools.py.

Fake API client — no server, no hosts.

Run: pytest tests/backend_server/test_group_tools.py -v
"""
import os
import sys

import pytest

_repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _repo_root)

from backend_server.src.mcp.tools.group_tools import GroupTools  # noqa: E402

pytestmark = pytest.mark.unit

HOSTS = {"success": True, "hosts": [
    {"host_name": "pi1", "status": "online", "devices": [
        {"device_id": "device1", "device_name": "A", "device_model": "stb", "remote_profiles": ["ir:stb"]},
        {"device_id": "device2", "device_name": "B", "device_model": "stb", "remote_profiles": ["ble:arris"]}]},
    {"host_name": "pi2", "status": "online", "devices": [
        {"device_id": "device1", "device_name": "C", "device_model": "stb", "remote_profiles": ["ir:stb"]}]},
]}


class FakeApi:
    def __init__(self, locked=()):
        self.posts = []
        self.locked = set(locked)

    def get(self, endpoint, params=None):
        return HOSTS

    def post(self, endpoint, data=None, params=None, timeout=None):
        self.posts.append((endpoint, data))
        if endpoint == "/server/control/takeControl":
            if (data["host_name"], data["device_id"]) in self.locked:
                return {"success": False, "errorType": "device_locked",
                        "owner_type": "manual_control", "owner_session_id": "other", "owner_user_name": "marie"}
            return {"success": True}
        if endpoint == "/server/remote/executeCommandGroup":
            return {"success": True, "skew_ms": 12, "results": [
                {"host_name": t["host_name"], "device_id": t["device_id"], "success": True, "ms": 50}
                for t in data["targets"]]}
        return {"success": True}


TARGETS = [{"host_name": "pi1", "device_id": "device1"}, {"host_name": "pi2", "device_id": "device1"}]


def test_list_device_groups_never_mixes_ir_and_ble():
    text = GroupTools(FakeApi()).list_device_groups({})["content"][0]["text"]
    assert "stb · ir:stb → 2 devices" in text
    assert "ble:arris" not in text


def test_execute_group_action_sends_once_per_action_and_releases():
    api = FakeApi()
    res = GroupTools(api).execute_group_action({
        "targets": TARGETS, "remote_profile": "ir:stb", "device_model": "stb", "team_id": "t",
        "actions": [{"command": "press_key", "params": {"key": "HOME"}},
                    {"command": "press_key", "params": {"key": "OK"}}]})
    sends = [d for e, d in api.posts if e == "/server/remote/executeCommandGroup"]
    assert [s["params"]["key"] for s in sends] == ["HOME", "OK"]
    assert sends[0]["remote_profile"] == "ir:stb"
    assert len(sends[0]["session_ids"]) == 2
    assert len([e for e, _ in api.posts if e == "/server/control/releaseControl"]) == 2
    assert res["isError"] is False
    assert "✓ pi2/device1" in res["content"][0]["text"]


def test_execute_group_action_skips_device_held_by_someone_else():
    api = FakeApi(locked={("pi2", "device1")})
    res = GroupTools(api).execute_group_action({
        "targets": TARGETS, "remote_profile": "ir:stb", "team_id": "t",
        "actions": [{"command": "press_key", "params": {"key": "HOME"}}]})
    sends = [d for e, d in api.posts if e == "/server/remote/executeCommandGroup"]
    assert sends[0]["targets"] == [TARGETS[0]]
    assert "pi2/device1 skipped" in res["content"][0]["text"]


def test_execute_group_action_needs_two_targets():
    res = GroupTools(FakeApi()).execute_group_action({"targets": TARGETS[:1], "remote_profile": "ir:stb",
                                                      "actions": [{"command": "press_key"}]})
    assert res["isError"] is True
