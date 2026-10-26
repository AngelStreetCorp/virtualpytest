"""Two browser-isolated web scripts can run on one host at the same time (TASK-146).

A web script that drives its OWN Chrome (its own debug port, its own profile) does not need
the host to itself. Before this, the second run was refused with 423 device_locked and queued
behind the first one, so two web scripts never ran at the same time on one host.

The device lock stays exclusive for everything else: a Take Control, and any script that drives
the host's own browser.
"""
import pytest

from backend_server.src.lib.utils import lock_utils
from backend_server.src.lib.utils.lock_utils import DeviceLockManager
from backend_server.src.routes.server_script_routes import _lock_held_by_browser_isolated_run

pytestmark = pytest.mark.unit

ISOLATED_REASON = 'script_execute:web/youtube_video_check.py#browser_isolated'
PLAIN_REASON = 'script_execute:web/youtube_video_check.py'


@pytest.fixture
def mgr(monkeypatch):
    monkeypatch.setattr(lock_utils.session_recorder, 'record_start', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(lock_utils.session_recorder, 'record_touch', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(lock_utils.session_recorder, 'record_end', lambda *a, **k: None, raising=False)
    return DeviceLockManager()


# ---------------------------------------------------------------------------
# Which lock may be run beside?
# ---------------------------------------------------------------------------

def test_an_isolated_script_run_is_recognised():
    assert _lock_held_by_browser_isolated_run({
        'owner_type': 'script_execution',
        'lock_reason': ISOLATED_REASON,
    }) is True


def test_a_normal_script_run_is_not_recognised():
    assert _lock_held_by_browser_isolated_run({
        'owner_type': 'script_execution',
        'lock_reason': PLAIN_REASON,
    }) is False


def test_a_take_control_is_never_run_beside():
    assert _lock_held_by_browser_isolated_run({
        'owner_type': 'manual_control',
        'lock_reason': 'manual_control',
    }) is False


def test_no_lock_is_never_run_beside():
    assert _lock_held_by_browser_isolated_run(None) is False
    assert _lock_held_by_browser_isolated_run({}) is False


# ---------------------------------------------------------------------------
# The lock itself: the first run holds it, the second one runs beside it
# ---------------------------------------------------------------------------

def test_the_first_isolated_run_takes_the_device_lock(mgr):
    out = mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-1', owner_job_id='job-1', lock_reason=ISOLATED_REASON,
    )
    assert out['success'] is True
    assert _lock_held_by_browser_isolated_run(out['lock_info']) is True


def test_the_second_isolated_run_is_refused_the_lock_but_may_run_beside_it(mgr):
    first = mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-1', owner_job_id='job-1', lock_reason=ISOLATED_REASON,
    )
    second = mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-2', owner_job_id='job-2', lock_reason=ISOLATED_REASON,
    )

    assert first['success'] is True
    # The lock stays with the first run: the second one gets no lock ...
    assert second['success'] is False
    assert second['error'] == 'device_locked'
    # ... but the device is not taken to itself, so the second run may go beside it.
    assert _lock_held_by_browser_isolated_run(second['conflict']) is True


def test_the_second_run_must_not_release_the_lock_of_the_first(mgr):
    mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-1', owner_job_id='job-1', lock_reason=ISOLATED_REASON,
    )
    # The parallel run ends and tries to release: it owns no lock, so nothing happens.
    released = mgr.release_lock(
        host_name='host-clone-2', device_id='host',
        owner_session_id='run-2', owner_type='script_execution', owner_job_id='job-2',
    )
    assert released.get('success') is False
    assert released.get('error') == 'not_lock_owner'

    # The run that holds the lock still releases it when it ends.
    released = mgr.release_lock(
        host_name='host-clone-2', device_id='host',
        owner_session_id='run-1', owner_type='script_execution', owner_job_id='job-1',
    )
    assert released.get('success') is True


def test_a_normal_script_run_still_blocks_the_device(mgr):
    mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-1', owner_job_id='job-1', lock_reason= PLAIN_REASON,
    )
    second = mgr.acquire_lock(
        host_name='host-clone-2', device_id='host', owner_type='script_execution',
        owner_session_id='run-2', owner_job_id='job-2', lock_reason= PLAIN_REASON,
    )
    assert second['success'] is False
    assert _lock_held_by_browser_isolated_run(second['conflict']) is False
