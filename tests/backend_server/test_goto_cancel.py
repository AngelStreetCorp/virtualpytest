"""
tests/backend_server/test_goto_cancel.py — Stop cancels a running goto (TASK-140 G7).

Server proxy route -> call_host path, MCP polling stops within one poll when the Atlas session is
cancelled, ToolBridge injects the private `_should_cancel` only for navigate_to_node.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

try:
    from backend_server.src.mcp.tools import navigation_tools  # noqa: E402
    from backend_server.src.routes import server_navigation_execution_routes as routes  # noqa: E402
    from backend_server.src.agent.core import tool_bridge as tb  # noqa: E402
except ImportError as exc:  # pragma: no cover - environment dependent
    pytest.skip(f"backend runtime deps not installed: {exc}", allow_module_level=True)

pytestmark = pytest.mark.unit


class _Api:
    def __init__(self, statuses=None):
        self.posts, self.gets = [], []
        self.statuses = statuses or []

    def post(self, endpoint, data=None, params=None, timeout=None):
        self.posts.append((endpoint, params))
        return {'success': True}

    def get(self, endpoint, params=None):
        self.gets.append(endpoint)
        return self.statuses.pop(0) if self.statuses else {'status': 'running', 'message': 'Step 2/4'}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(navigation_tools.time, 'sleep', lambda s: None)


def test_poll_stops_and_cancels_when_session_cancelled():
    api = _Api()
    tools = navigation_tools.NavigationTools(api)
    flags = iter([False, False, True])
    resp = tools._poll_navigation_completion('exec-1', 'device1', 'h', 't', 'home',
                                             should_cancel=lambda: next(flags))
    assert resp['isError'] is False
    assert 'stopped by the user' in resp['content'][0]['text']
    assert [e for e, _ in api.posts] == ['/server/navigation/execution/exec-1/cancel']
    assert api.posts[0][1] == {'device_id': 'device1', 'host_name': 'h', 'team_id': 't'}
    assert len(api.gets) == 3  # 2 normal polls + 1 status read for the message


def test_poll_without_cancel_check_unchanged():
    api = _Api([{'status': 'completed', 'result': {'message': 'ok', 'already_at_target': True}}])
    resp = navigation_tools.NavigationTools(api)._poll_navigation_completion('e', 'd', 'h', 't', 'home')
    assert resp['isError'] is False and api.posts == []


def test_poll_reports_cancelled_status():
    api = _Api([{'status': 'cancelled', 'message': 'Navigation cancelled before step 2/3'}])
    resp = navigation_tools.NavigationTools(api)._poll_navigation_completion('e', 'd', 'h', 't', 'home')
    assert resp['isError'] is False and 'stopped' in resp['content'][0]['text']


def test_navigate_to_node_pops_private_key(monkeypatch):
    api = _Api()
    api.resolve_userinterface_name = lambda n, t: ('tree', 'ui', 'm', None)
    seen = {}
    tools = navigation_tools.NavigationTools(api)
    monkeypatch.setattr(tools, '_auto_lock', lambda *a, **k: None)
    monkeypatch.setattr(tools, '_auto_unlock', lambda *a, **k: None)
    monkeypatch.setattr(tools, '_localize_off', lambda *a, **k: True)
    monkeypatch.setattr(tools, '_report_position', lambda response, *a, **k: response)

    def poll(execution_id, *a, should_cancel=None, **k):
        seen['cancel'] = should_cancel
        return {'content': [], 'isError': False}
    monkeypatch.setattr(tools, '_poll_navigation_completion', poll)
    api.post = lambda endpoint, data=None, params=None, timeout=None: (
        seen.update(data=data, params=params) or {'success': True, 'execution_id': 'x'})
    cb = lambda: True  # noqa: E731
    params = {'host_name': 'h', 'device_id': 'd', 'userinterface_name': 'yt',
              'target_node_label': 'home', 'team_id': 't', '_should_cancel': cb}
    tools.navigate_to_node(params)
    assert seen['cancel'] is cb
    assert '_should_cancel' not in params
    assert '_should_cancel' not in seen['data'] and '_should_cancel' not in seen['params']


def test_server_route_proxies_cancel_to_host(monkeypatch):
    from flask import Flask
    calls = []
    monkeypatch.setattr(routes, 'proxy_to_host_with_params',
                        lambda endpoint, method='GET', data=None, query_params=None, timeout=30:
                        calls.append((endpoint, method, query_params)) or ({'success': True}, 200))
    app = Flask(__name__)
    app.register_blueprint(routes.server_navigation_execution_bp)
    client = app.test_client()
    r = client.post('/server/navigation/execution/abc/cancel?device_id=device1&host_name=h&team_id=t')
    assert r.status_code == 200
    assert calls == [('/host/navigation/execution/abc/cancel', 'POST', {'device_id': 'device1', 'team_id': 't'})]
    assert client.post('/server/navigation/execution/abc/cancel').status_code == 400


def _bridge(monkeypatch, session):
    seen = {}
    fake_mcp = SimpleNamespace(
        HIDDEN_TOOLS=(),
        handle_tool_call=lambda name, params: seen.update(name=name, params=params) or {'content': []})
    monkeypatch.setattr(tb, 'get_mcp_server', lambda: fake_mcp)
    bridge = tb.ToolBridge(session=session)
    monkeypatch.setattr(bridge, 'get_available_tool_names', lambda: ['navigate_to_node', 'list_hosts'])
    return bridge, seen


def test_toolbridge_injects_should_cancel_for_navigate_only(monkeypatch):
    session = SimpleNamespace(id='s', cancelled=False, context={})
    bridge, seen = _bridge(monkeypatch, session)
    original = {'host_name': 'h', 'device_id': 'd'}
    bridge.execute('navigate_to_node', original)
    check = seen['params']['_should_cancel']
    assert '_should_cancel' not in original
    assert check() is False
    session.cancelled = True
    assert check() is True
    bridge.execute('list_hosts', {})
    assert '_should_cancel' not in seen['params']
