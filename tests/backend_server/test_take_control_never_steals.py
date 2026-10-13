"""Taking control of a device another session holds is refused, never a takeover (BUG-0402).

Regression guards (2026-10-04 incident, vpt-pi1 device1):
- scripts/atlas_chat.py --host/--device took the device with POST /server/control/takeover
  (stop_running_execution=True), which preempts any manual lock and stops a running
  script, and kept chatting when that failed. It now takes the normal /takeControl lock
  and exits 3 when the server answers 423.
- The MCP take_control tool silently fell back to /takeover when a script held the
  device (allow_takeover defaulted to True). Takeover is now opt-in only.

No server: HTTP and the MCP API client are fakes.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit

LOCKED = {
    'success': False,
    'errorType': 'device_locked',
    'owner_type': 'manual_control',
    'owner_session_id': 'other-session',
    'owner_user_name': 'someone',
}


def _load_atlas_chat():
    pytest.importorskip('socketio')
    pytest.importorskip('requests')
    spec = importlib.util.spec_from_file_location('atlas_chat', REPO / 'scripts' / 'atlas_chat.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.content = b'x'

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


def test_atlas_chat_takes_the_normal_lock_not_a_takeover(monkeypatch):
    mod = _load_atlas_chat()
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return _Resp(200, {'success': True})

    monkeypatch.setattr(mod.requests, 'post', fake_post)
    mod.take_device_control('https://srv', True, None, 'vpt-pi1', 'device1', 'sess-1')
    assert calls == ['https://srv/server/control/takeControl']


def test_atlas_chat_refuses_a_device_held_by_another_session(monkeypatch):
    mod = _load_atlas_chat()
    posted = []

    def fake_post(url, **kw):
        posted.append(url)
        return _Resp(423, LOCKED)

    monkeypatch.setattr(mod.requests, 'post', fake_post)
    args = SimpleNamespace(server='https://srv', insecure=False, host='vpt-pi1', device='device1',
                           lease_checked=True, auto_sign=None)
    monkeypatch.setattr(mod, 'create_session', lambda *a: 'sess-1')
    monkeypatch.setattr(mod, '_chat', lambda *a: pytest.fail('chatted against a locked device'))

    assert mod.run(args) == 3
    assert posted == ['https://srv/server/control/takeControl']  # no takeover, no release


class _FakeApi:
    def __init__(self):
        self.posts = []

    def post(self, path, data=None, params=None):
        self.posts.append(path)
        if path == '/server/control/takeControl':
            return {**LOCKED, 'owner_type': 'script_execution'}
        return {'success': True}


def _control_tools():
    try:
        from backend_server.src.mcp.tools.control_tools import ControlTools
    except ImportError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f'MCP runtime deps not installed: {exc}')
    api = _FakeApi()
    return ControlTools(api), api


def test_mcp_take_control_does_not_take_over_a_running_script():
    tools, api = _control_tools()
    result = tools.take_control({'host_name': 'vpt-pi1', 'device_id': 'device1', 'team_id': 't'})
    assert api.posts == ['/server/control/takeControl']
    assert result.get('isError') is True


def test_mcp_take_control_takes_over_only_when_asked():
    tools, api = _control_tools()
    tools.take_control({'host_name': 'vpt-pi1', 'device_id': 'device1', 'team_id': 't',
                        'allow_takeover': True})
    assert api.posts == ['/server/control/takeControl', '/server/control/takeover']


class _ManualLockApi:
    """The live takeControl 423 shape: holder details nested in lock_info."""

    def __init__(self):
        self.posts = []

    def post(self, path, data=None, params=None):
        self.posts.append(path)
        return {'success': False, 'errorType': 'device_locked',
                'error': 'Device host-clone-1:host is locked',
                'lock_info': {'owner_type': 'manual_control', 'owner_session_id': 'browser-1',
                              'owner_user_name': 'Auto Signed'}}


def test_mcp_take_control_conflict_names_the_holder():
    tools, _ = _control_tools()
    api = _ManualLockApi()
    tools.api = api
    result = tools.take_control({'host_name': 'host-clone-1', 'device_id': 'host', 'team_id': 't'})
    text = result['content'][0]['text']
    assert result.get('isError') is True and result.get('errorType') == 'device_locked'
    assert "is in use by Auto Signed (manual_control). Not taking it over" in text
    assert api.posts == ['/server/control/takeControl']
