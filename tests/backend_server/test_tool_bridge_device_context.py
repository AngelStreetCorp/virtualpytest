"""Agent tool bridge: a device tool called without host_name/device_id gets the chat's own device (TASK-135).

Sonnet dropped host_name from dump_ui_elements in 1 of 5 web tree builds ("host_name required"), costing a turn.
A value the model gives is kept; tools that are not device tools are never filled.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.agent.core import tool_bridge as tb  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"agent runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


def _bridge(context):
    bridge = object.__new__(tb.ToolBridge)
    bridge.session = SimpleNamespace(id='s1', context=context)
    return bridge


CTX = {'host_name': 'host-clone-1', 'device_id': 'host'}


def test_missing_host_and_device_come_from_the_chat():
    params = {'platform': 'web'}
    _bridge(dict(CTX))._fill_device_context('dump_ui_elements', params)
    assert params == {'platform': 'web', 'host_name': 'host-clone-1', 'device_id': 'host'}


def test_a_named_device_is_kept():
    params = {'host_name': 'vpt-pi1', 'device_id': 'device1'}
    _bridge(dict(CTX))._fill_device_context('navigate_to_node', params)
    assert params == {'host_name': 'vpt-pi1', 'device_id': 'device1'}


def test_other_tools_are_not_filled():
    params = {}
    _bridge(dict(CTX))._fill_device_context('list_scripts', params)
    assert params == {}


def test_no_chat_device_no_fill():
    params = {}
    _bridge({})._fill_device_context('capture_screenshot', params)
    assert params == {}
