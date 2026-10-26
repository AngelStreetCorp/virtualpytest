"""A script launch may run under its own user's Take Control (allow_same_user_takeover), but the built-in default
user id is shared by every API-key / auto-sign / anonymous caller: a CI smoke with the service key ran under a
benchmark harness's take-control lock and drove its browser mid-run (TASK-135)."""
import pytest

from backend_server.src.lib.utils import lock_utils
from backend_server.src.lib.utils.lock_utils import DeviceLockManager

pytestmark = pytest.mark.unit

REAL = '3f2b8c1e-6a4d-4e0b-9a7f-2c5d8e1f0a11'


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(lock_utils.session_recorder, 'record_start', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(lock_utils.session_recorder, 'record_touch', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(lock_utils.session_recorder, 'record_end', lambda *a, **k: None, raising=False)
    return DeviceLockManager()


def _take(mgr, user):
    assert mgr.acquire_lock(host_name='host-clone-1', device_id='host', owner_type='manual_control',
                            owner_session_id='harness', owner_user_id=user)['success']


def _script(mgr, user):
    return mgr.acquire_lock(host_name='host-clone-1', device_id='host', owner_type='script_execution',
                            owner_session_id='ci-smoke', owner_user_id=user, allow_same_user_takeover=True)


def test_shared_default_user_does_not_run_under_another_take_control(mgr):
    _take(mgr, 'default-user')
    out = _script(mgr, 'default-user')
    assert out['success'] is False and out['error'] == 'device_locked'


def test_the_same_personal_user_still_runs_under_its_take_control(mgr):
    _take(mgr, REAL)
    out = _script(mgr, REAL)
    assert out['success'] is True and out.get('subordinate') is True
