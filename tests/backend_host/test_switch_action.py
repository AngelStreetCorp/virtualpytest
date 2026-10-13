"""Action executor routes `switch` actions to the device's switch controller (TASK-51).

The action executor lives behind the host services, so we exercise the dispatch branch directly
on an instance bound to a fake device with a fake switch controller. The contract is exactly the
one ``backend_host/src/services/actions/action_executor.py`` writes today: ``send_command(command,
**params)`` with the action's params as keyword args, and ``{'success': False, 'error': ...}`` when
no controller is wired.
"""
import asyncio
import sys
import os

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_test_dir, "..", "..")))


class _FakeSwitchController:
    """Minimal stand-in for ``BluetoothProconSwitchController.send_command``."""

    def __init__(self):
        self.calls = []

    def send_command(self, command, **kwargs):
        self.calls.append({"command": command, "kwargs": dict(kwargs)})
        return {"success": True, "echo": command, "kwargs": dict(kwargs)}


class _FakeDevice:
    """The ActionExecutor only reads host_name, device_id, device_model, device_name and _get_controller()."""

    def __init__(self, switch=None):
        self.host_name = "test-host"
        self.device_id = "device-test"
        self.device_model = "nintendo_switch"
        self.device_name = "switch-test"
        self._switch = switch
        self.navigation_context = {}
        self.get_capture_dir = lambda subfolder="": "/tmp"

    def _get_controller(self, name):
        if name == "switch":
            return self._switch
        return None


def _executor(device):
    """Build an ActionExecutor without going through device init."""
    from backend_host.src.services.actions.action_executor import ActionExecutor
    return ActionExecutor(device, _from_device_init=True)


def test_switch_action_calls_send_command_with_command_and_params():
    controller = _FakeSwitchController()
    device = _FakeDevice(switch=controller)
    exe = _executor(device)

    action = {
        "command": "sequence:[left,b,b]",
        "action_type": "switch",
        "params": {"hold_ms": 50, "gap_ms": 40, "wait_time": 0},
    }
    result = asyncio.run(exe._execute_single_action(
        action=action, execution_order=1, action_number=1, action_category="test",
        team_id="t", context=None))

    assert controller.calls, "switch controller send_command was not called"
    call = controller.calls[0]
    assert call["command"] == "sequence:[left,b,b]"
    assert call["kwargs"].get("hold_ms") == 50
    assert call["kwargs"].get("gap_ms") == 40
    assert call["kwargs"].get("wait_time") == 0
    assert result["success"] is True


def test_switch_action_reports_missing_controller():
    device = _FakeDevice(switch=None)
    exe = _executor(device)

    action = {
        "command": "press:b",
        "action_type": "switch",
        "params": {"wait_time": 0},
    }
    result = asyncio.run(exe._execute_single_action(
        action=action, execution_order=1, action_number=1, action_category="test",
        team_id="t", context=None))

    assert result["success"] is False
    assert "Switch controller not available" in result.get("error", "")