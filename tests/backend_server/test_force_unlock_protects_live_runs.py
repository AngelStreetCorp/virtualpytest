"""force_unlock never aborts another caller's live run (BUG-0679).

In-memory: lock info and the host's is_busy / abort calls are mocked.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

pytestmark = pytest.mark.unit

LOCK = {
    'owner_type': 'script_execution', 'owner_session_id': 'ci-session', 'owner_user_id': 'ci-user',
    'owner_user_name': 'CI', 'lock_reason': 'vpt/smoke_device_control', 'locked_at': 1760870000.0,
}


@pytest.fixture
def lu(monkeypatch):
    try:
        from backend_server.src.lib.utils import lock_utils
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f'server deps not installed: {exc}')
    state = {'lock': dict(LOCK), 'busy': True, 'aborts': 0, 'released': 0}
    monkeypatch.setattr(lock_utils, 'get_device_lock_info', lambda h, d=None: state['lock'])

    def fake_call_host(host, path, method='GET', **kw):
        return {'busy': state['busy'], 'active_jobs': [{'type': 'script'}] if state['busy'] else []}, 200
    import shared.src.lib.utils.build_url_utils as bu
    monkeypatch.setattr(bu, 'call_host', fake_call_host)

    def fake_abort(host_data, device_id, owner_type):
        state['aborts'] += 1
        return {'success': True, 'aborted': True, 'details': {}}
    monkeypatch.setattr(lock_utils, 'abort_running_execution', fake_abort)

    def fake_release(h, d=None):
        state['released'] += 1
        state['lock'] = None
        return {'success': True, 'released': True}
    monkeypatch.setattr(lock_utils, 'force_unlock_device', fake_release)

    import backend_server.src.lib.utils.server_utils as su
    class HM:
        def get_host(self, name):
            return {'host_name': name}
    monkeypatch.setattr(su, 'get_host_manager', lambda: HM())
    return lock_utils, state


def _force(lu_mod, **kw):
    return lu_mod.abort_and_force_unlock('host-clone-1:host', 'device1', strict=True, protect_others=True, **kw)


def test_stale_lock_is_cleared(lu):
    mod, state = lu
    state['busy'] = False  # host runs nothing: the lock is a zombie
    result = _force(mod, caller_sessions=['forge'], caller_user_id='forge-user')
    assert result['success'] and result['released']
    assert state['released'] == 1


def test_own_lock_is_cleared_and_aborted(lu):
    mod, state = lu
    result = _force(mod, caller_sessions=['ci-session'])
    assert result['success'] and result['released']
    assert state['aborts'] == 1


def test_other_owners_live_script_is_not_aborted_and_refusal_names_it(lu):
    mod, state = lu
    result = _force(mod, caller_sessions=['forge'], caller_user_id='forge-user')
    assert not result['success'] and result['errorType'] == 'device_busy'
    msg = result['error']
    assert 'device busy' in msg and 'vpt/smoke_device_control' in msg and 'CI' in msg
    assert "does not abort another caller's live run" in msg
    assert state['aborts'] == 0 and state['released'] == 0
    assert state['lock'] is not None


def test_human_path_without_protect_others_still_aborts(lu):
    mod, state = lu
    result = mod.abort_and_force_unlock('host-clone-1:host', 'device1', strict=False)
    assert result['success'] and state['aborts'] == 1


def test_shared_default_user_id_is_not_ownership(lu):
    mod, state = lu
    from shared.src.lib.utils.app_utils import DEFAULT_USER_ID
    state['lock']['owner_user_id'] = DEFAULT_USER_ID
    result = _force(mod, caller_sessions=['forge'], caller_user_id=DEFAULT_USER_ID)
    assert not result['success'] and result['errorType'] == 'device_busy'
    assert state['aborts'] == 0


def test_personal_user_id_match_is_ownership(lu):
    mod, state = lu
    result = _force(mod, caller_sessions=['other-tab'], caller_user_id='ci-user')
    assert result['success'] and state['aborts'] == 1


def test_fresh_lock_with_nothing_registered_yet_is_a_starting_run(lu):
    import time
    mod, state = lu
    state['busy'] = False
    state['lock']['locked_at'] = time.time() - 3
    result = _force(mod, caller_sessions=['forge'])
    assert not result['success'] and result['errorType'] == 'device_busy'
    assert state['released'] == 0
