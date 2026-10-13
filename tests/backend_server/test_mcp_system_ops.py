"""
Unit tests for the 2 remaining MCP tools in system_ops_tools.py
(post-de-dupe: list_services and restart_service were moved to masterchief):
- check_storage
- ping_host

The tests do not hit a live backend_host. They use a fake API client
(`_FakeAPI`) that returns canned responses, so the assertions are about
the MCP tool's parameter wiring + response formatting, not the underlying
host route.
"""
import pytest

pytestmark = pytest.mark.unit


class _FakeAPI:
    """In-process stand-in for MCPAPIClient.

    Records the last (method, path, body, params) tuple and returns a
    pre-canned response. Default responses model the success case for
    every method; the `set_response(...)` method lets a test swap in a
    different one.
    """

    def __init__(self, default_response):
        self.default_response = default_response
        self.calls = []

    def set_response(self, response):
        self.default_response = response

    def get(self, path, params=None, **kwargs):
        self.calls.append(('GET', path, params))
        return self.default_response

    def post(self, path, body=None, **kwargs):
        self.calls.append(('POST', path, body))
        return self.default_response


def _make_tools(api):
    from backend_server.src.mcp.tools.system_ops_tools import SystemOpsTools
    from backend_server.src.mcp.utils.mcp_formatter import MCPFormatter
    return SystemOpsTools(api)


# --- check_storage ----------------------------------------------------------

def test_check_storage_formats_human_readable_table():
    # 200 GB total, 100 GB used, 100 GB free, 50% used.
    api = _FakeAPI({
        'success': True,
        'host': 'vpt-pi3',
        'rows': [{
            'filesystem': '/dev/root',
            'size': 200 * 1024**3,
            'used': 100 * 1024**3,
            'available': 100 * 1024**3,
            'use_pct': 50.0,
            'mountpoint': '/',
        }],
    })
    tools = _make_tools(api)
    result = tools.check_storage({'host_name': 'vpt-pi3'})

    assert result['isError'] is False
    assert ('GET', '/host/system/checkStorage', {'host_name': 'vpt-pi3'}) in api.calls
    text = result['content'][0]['text']
    assert 'vpt-pi3' in text
    assert '100.0G' in text
    assert '50' in text
    assert '✅' in text   # 50% is the OK icon


def test_check_storage_warns_at_90_percent():
    api = _FakeAPI({
        'success': True,
        'host': 'vpt-pi3',
        'rows': [{
            'filesystem': '/dev/root',
            'size': 100 * 1024**3,
            'used': 95 * 1024**3,
            'available': 5 * 1024**3,
            'use_pct': 95.0,
            'mountpoint': '/',
        }],
    })
    tools = _make_tools(api)
    result = tools.check_storage({'host_name': 'vpt-pi3'})
    assert '🔴' in result['content'][0]['text']  # >= 90% → critical


# --- ping_host --------------------------------------------------------------

def test_ping_host_reports_up_with_rtt():
    api = _FakeAPI({
        'success': True, 'host': 'vpt-pi3', 'rtt_ms': 3.21,
        'backend_port': 6109, 'boot_time': '2026-10-09T07:00:00Z',
    })
    tools = _make_tools(api)
    result = tools.ping_host({'host_name': 'vpt-pi3'})

    assert result['isError'] is False
    assert '✅' in result['content'][0]['text']
    assert 'vpt-pi3' in result['content'][0]['text']
    assert '3.21' in result['content'][0]['text']


def test_ping_host_reports_down_without_isError():
    # success=False here means the TCP connect failed — the tool still
    # answers the question (it's just a negative answer). isError is False
    # because the tool itself did not raise.
    api = _FakeAPI({
        'success': False, 'host': 'vpt-pi3', 'rtt_ms': 200.0,
        'backend_port': 6109, 'error': 'Connection refused',
    })
    tools = _make_tools(api)
    result = tools.ping_host({'host_name': 'vpt-pi3'})

    assert result['isError'] is False
    assert '🔴' in result['content'][0]['text']
    assert 'NOT reachable' in result['content'][0]['text']
