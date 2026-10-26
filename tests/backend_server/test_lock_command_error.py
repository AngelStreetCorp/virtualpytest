"""take_control / release_control sent as an action command get a clear answer (TASK-163).

Atlas put {"command": "take_control"} into execute_group_action; the BLE controller answered
"unknown command: take_control". The tools now refuse it up front and name the tool to call.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

pytestmark = pytest.mark.unit


def _fn():
    try:
        from backend_server.src.mcp.utils.lock_ownership import lock_command_error
    except ImportError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"backend deps missing: {exc}")
    return lock_command_error


def test_take_control_action_is_refused_with_the_tool_name():
    err = _fn()([{'command': 'take_control'}])
    assert err['isError']
    text = err['content'][0]['text']
    assert 'take_control' in text and 'tool' in text


def test_press_key_actions_pass():
    assert _fn()([{'command': 'press_key', 'params': {'key': 'HOME'}}]) is None
    assert _fn()([]) is None


def test_bare_string_lock_action_is_refused():
    assert _fn()(['take_control'])['isError']


def test_imperative_naming_a_device_skips_the_faq():
    from backend_server.src.agent import quick_step as qs
    devices = [{"device_name": "stb3"}]
    assert qs.is_device_command("Press HOME on stb3", devices)
    assert qs.is_device_command("Take control of stb3", devices)
    assert not qs.is_device_command("How does HOME work on a set-top box?", devices)
    assert not qs.is_device_command("Press HOME on the remote", devices)
