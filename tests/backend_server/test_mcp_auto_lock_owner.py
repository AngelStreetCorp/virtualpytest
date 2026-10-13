"""MCP device tools run only under the caller's own lock, never someone else's (BUG-0402).

execute_device_action / navigate_to_node / execute_testcase used to proceed whenever the
device held ANY manual_control lock ("piggyback"), so an Atlas chat or an MCP client could
drive a device another person had taken control of. They now run under a lock only when it
is the caller's own (same session, the chat's browser tab, or the same signed-in user), and
otherwise refuse and name the holder. force_unlock never clears another person's Take Control.

No server: the MCP API client is a fake that answers takeControl like the real route.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit


def _lock_ownership():
    try:
        from backend_server.src.mcp.utils import lock_ownership
    except ImportError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f'MCP runtime deps not installed: {exc}')
    return lock_ownership


def _held_by(session='browser-alice', user='user-alice', name='Alice', owner_type='manual_control'):
    return {
        'success': False,
        'errorType': 'device_locked',
        'owner_type': owner_type,
        'owner_session_id': session,
        'owner_user_id': user,
        'owner_user_name': name,
    }


class _FakeApi:
    """takeControl answers with `lock` (a 423 payload) or success when the device is free."""

    def __init__(self, lock=None):
        self.lock = lock
        self.posts = []

    def post(self, path, data=None, params=None):
        self.posts.append((path, dict(data or {})))
        if path == '/server/control/takeControl':
            if not self.lock:
                return {'success': True}
            if self.lock['owner_session_id'] == (data or {}).get('session_id'):
                return {'success': True, 'reused': True}
            return dict(self.lock)
        return {'success': True}

    def paths(self):
        return [p for p, _ in self.posts]


def _auto_lock(api, params, force_unlock=False):
    lo = _lock_ownership()
    held = {}
    err = lo.auto_lock(api, held, params, 'vpt-pi1', 'device1', 't', force_unlock, 'test')
    return err, held


@pytest.fixture(autouse=True)
def _no_anonymous_sessions():
    lo = _lock_ownership()
    lo._ANONYMOUS_MCP_SESSIONS.clear()
    yield
    lo._ANONYMOUS_MCP_SESSIONS.clear()


def test_someone_elses_take_control_is_refused_and_names_the_holder():
    # Fails on the old code: it piggybacked on any manual_control lock.
    api = _FakeApi(_held_by())
    err, held = _auto_lock(api, {'session_id': 'chat-bob', '_caller_user_id': 'user-bob'})
    assert err and err['isError'] and err['errorType'] == 'device_locked'
    assert 'Alice' in err['content'][0]['text']
    assert held == {}


def test_an_mcp_client_with_no_identity_is_refused_too():
    err, _ = _auto_lock(_FakeApi(_held_by()), {})
    assert err and 'Alice' in err['content'][0]['text']


def test_force_unlock_never_clears_another_persons_take_control():
    api = _FakeApi(_held_by())
    err, _ = _auto_lock(api, {'session_id': 'chat-bob'}, force_unlock=True)
    assert err
    assert api.paths() == ['/server/control/takeControl']  # no takeover, no forceUnlock


def test_force_unlock_still_stops_a_running_script_when_asked():
    api = _FakeApi(_held_by(session='job-1', user=None, name=None, owner_type='script_execution'))
    err, held = _auto_lock(api, {'session_id': 'chat-bob'}, force_unlock=True)
    assert err is None
    assert api.paths() == ['/server/control/takeControl', '/server/control/takeover']
    assert held == {'vpt-pi1:device1': 'chat-bob'}


@pytest.mark.parametrize('params', [
    {'session_id': 'browser-alice'},                                         # MCP: session from take_control
    {'session_id': 'chat-1', '_caller_browser_session_id': 'browser-alice'},  # Atlas: the chat's own tab
    {'session_id': 'chat-1', '_caller_user_id': 'user-alice'},                # Atlas: same signed-in user
])
def test_the_callers_own_take_control_is_used_and_not_released(params):
    err, held = _auto_lock(_FakeApi(_held_by()), params)
    assert err is None
    assert held == {}  # not ours to release after the call


def test_a_free_device_is_locked_for_the_call_under_the_callers_session():
    api = _FakeApi()
    err, held = _auto_lock(api, {'session_id': 'chat-1', '_caller_user_id': 'user-bob'})
    assert err is None
    assert held == {'vpt-pi1:device1': 'chat-1'}
    assert api.posts[0][1]['user_id'] == 'user-bob'


def test_anonymous_mcp_take_control_then_action_runs_under_that_lock():
    try:
        from backend_server.src.mcp.tools.control_tools import ControlTools
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'MCP runtime deps not installed: {exc}')
    api = _FakeApi()
    ControlTools(api).take_control({'host_name': 'vpt-pi1', 'device_id': 'device1', 'team_id': 't'})
    mcp_session = api.posts[0][1]['session_id']
    api.lock = _held_by(session=mcp_session, user=None, name=None)

    err, held = _auto_lock(api, {})
    assert err is None and held == {}

    # A chat (explicit identity) does not inherit the anonymous MCP client's lock.
    err, _ = _auto_lock(api, {'session_id': 'chat-1', '_caller_user_id': 'user-bob'})
    assert err


def test_execute_testcase_does_not_run_under_someone_elses_take_control():
    try:
        from backend_server.src.mcp.tools.testcase_tools import TestCaseTools
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'MCP runtime deps not installed: {exc}')

    class _Api(_FakeApi):
        def post(self, path, data=None, params=None):
            self.posts.append((path, dict(data or {})))
            return dict(self.lock)

    api = _Api(_held_by())
    result = TestCaseTools(api).execute_testcase({
        'testcase_name': 'tc', 'host_name': 'vpt-pi1', 'device_id': 'device1', 'team_id': 't',
        'graph_json': {'nodes': []}, 'session_id': 'chat-bob',
    })
    assert result['isError'] and 'Alice' in result['content'][0]['text']
    assert api.paths() == ['/server/testcase/execute']  # no retry under Alice's session


def test_execute_device_action_does_not_drive_a_device_someone_else_controls():
    # Through the public tool, so it also runs (and fails) against the pre-fix code.
    try:
        from backend_server.src.mcp.tools.action_tools import ActionTools
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'MCP runtime deps not installed: {exc}')

    class _Api(_FakeApi):
        def get(self, path, params=None):
            return {}

    api = _Api(_held_by())
    result = ActionTools(api).execute_device_action({
        'host_name': 'vpt-pi1', 'device_id': 'device1', 'team_id': 't', 'session_id': 'chat-bob',
        'actions': [{'command': 'press_key', 'action_type': 'remote', 'params': {'key': 'OK'}}],
    })
    assert '/server/action/executeBatch' not in api.paths()
    assert result['isError'] and 'Alice' in result['content'][0]['text']
