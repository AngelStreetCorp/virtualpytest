"""Resume is not complete until the bonded STB can carry HID keys."""

import importlib

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def ctl(monkeypatch):
    mod = importlib.import_module('backend_host.src.controllers.remote.bluetooth')
    c = object.__new__(mod.BluetoothRemoteController)
    c.device_type = 'bluetooth'
    c._script_running = False
    c._resume_state = 'idle'
    c._resume_error = None
    c.runs = []
    c.ready = True
    c.ready_timeouts = []
    c._run_script = lambda name: (c.runs.append(name), (True, 'ok'))[1]
    c.wait_for_ready = lambda timeout: (
        c.ready_timeouts.append(timeout), c.ready)[1]

    class InlineThread:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(mod.threading, 'Thread', InlineThread)
    return c


def test_resume_runs_script_then_requires_ready_link(ctl):
    result = ctl.resume()

    assert result == {'success': True, 'output': 'BLE resume recovery started'}
    assert ctl.runs == ['resume.sh']
    assert ctl.ready_timeouts == [ctl.WAKE_TIMEOUT_S * ctl._MAX_WAKE_TARGETS + 10]
    assert ctl._resume_state == 'ready'
    assert ctl._resume_error is None
    assert ctl._script_running is False


def test_resume_reports_link_timeout_as_failure(ctl):
    ctl.ready = False

    ctl.resume()

    assert ctl._resume_state == 'failed'
    assert 'did not reach connected + services + HID ready' in ctl._resume_error
    assert ctl._script_running is False


def test_resume_reports_script_failure_without_waking(ctl):
    ctl._run_script = lambda name: (False, 'ERROR: adapter reset failed')

    ctl.resume()

    assert ctl.ready_timeouts == []
    assert ctl._resume_state == 'failed'
    assert 'adapter reset failed' in ctl._resume_error


def test_resume_rejects_overlap(ctl):
    ctl._resume_state = 'running'

    assert ctl.resume() == {
        'success': False,
        'error': 'Resume recovery already in progress',
    }
