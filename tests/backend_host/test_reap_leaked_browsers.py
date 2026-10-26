"""A browser left behind by a dead run must be closed, safely (BUG-0837 follow-up).

`browser_run_slots.leaked_browser_ports()` reports browsers that belong to no live run and
never touches them; `browser_run_status()` counts them. A run releases its slot whether or not
its Chrome died, so every corpse is invisible to the cap except as a leak count -- a host that
only leaks eventually refuses new browser runs outright. `reap_leaked_browsers()` is the
deliberate half.

The rules it must not break, and the reasons:

  - the host's own service browser on 9222 is never a leak, so never a target,
  - a port a live run owns is refused inside `ChromeManager.shutdown_chrome`, so a run that
    starts between the scan and the kill is never touched,
  - a process group is signalled only when the target leads one, so the vpt-host service's
    group is unreachable (killing a shared group took a lab host's SSH down on 2026-10-22).

Run: pytest tests/backend_host/test_reap_leaked_browsers.py -v
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, '..', '..'))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

pytestmark = pytest.mark.unit

REAPER = 'backend_host.src.lib.utils.playwright_utils'


@pytest.fixture
def reaper(monkeypatch):
    """The reaper with its detector and its kill swapped for recorders."""
    from backend_host.src.lib.utils import playwright_utils
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (), raising=False)
    monkeypatch.delenv('VPT_REAP_LEAKED_BROWSERS', raising=False)
    return playwright_utils


def test_it_closes_exactly_the_ports_the_detector_names(reaper, monkeypatch):
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (9300, 9301), raising=False)
    killed = []
    monkeypatch.setattr(reaper.ChromeManager, 'shutdown_chrome', staticmethod(lambda p: killed.append(p) or True))

    assert reaper.reap_leaked_browsers() == [9300, 9301]
    assert killed == [9300, 9301]


def test_the_service_browser_on_9222_is_never_a_target(reaper, monkeypatch):
    """9222 belongs to the host's own service browser (agent tree, web worker, KPI executor)."""
    import shared.src.lib.utils.browser_run_slots as slots
    from shared.src.lib.utils.browser_port_allocator import RESERVED_DEBUG_PORT

    assert RESERVED_DEBUG_PORT == 9222
    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (9222,), raising=False)
    killed = []
    monkeypatch.setattr(reaper.ChromeManager, 'shutdown_chrome', staticmethod(lambda p: killed.append(p) or True))

    reaper.reap_leaked_browsers()
    assert killed == []


def test_it_still_goes_through_shutdown_chrome_rather_than_killing_itself(reaper, monkeypatch):
    """shutdown_chrome is what refuses a live owner and what keeps the kill off the service
    group; reaping must delegate to it instead of signalling anything directly."""
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (9300,), raising=False)
    monkeypatch.setattr(reaper.ChromeManager, 'shutdown_chrome', staticmethod(lambda p: False))

    assert reaper.reap_leaked_browsers() == []


def test_the_operator_kill_switch_stops_it(reaper, monkeypatch):
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (9300,), raising=False)
    monkeypatch.setattr(reaper.ChromeManager, 'shutdown_chrome', staticmethod(lambda p: True))
    for value in ('0', 'off', 'false', 'no'):
        monkeypatch.setenv('VPT_REAP_LEAKED_BROWSERS', value)
        assert reaper.reap_leaked_browsers() == []
    monkeypatch.setenv('VPT_REAP_LEAKED_BROWSERS', '1')
    assert reaper.reap_leaked_browsers() == [9300]


def test_one_bad_port_does_not_stop_the_others(reaper, monkeypatch):
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: (9300, 9301, 9302), raising=False)

    def flaky(port):
        if port == 9301:
            raise RuntimeError('browser already gone')
        return True

    monkeypatch.setattr(reaper.ChromeManager, 'shutdown_chrome', staticmethod(flaky))
    assert reaper.reap_leaked_browsers() == [9300, 9302]


def test_a_detector_that_cannot_run_is_survivable(reaper, monkeypatch):
    """The host must keep running its jobs when the scan is unavailable."""
    import shared.src.lib.utils.browser_run_slots as slots

    def boom():
        raise RuntimeError('no /proc')

    monkeypatch.setattr(slots, 'leaked_browser_ports', boom, raising=False)
    assert reaper.reap_leaked_browsers() == []


def test_the_scheduler_job_never_lets_a_reap_failure_reach_apscheduler(monkeypatch):
    """A job that raises is dropped by APScheduler and silently stops reaping for ever."""
    from backend_host.src.services import deployment_scheduler as ds
    from backend_host.src.lib.utils import playwright_utils

    def explode():
        raise RuntimeError('boom')

    monkeypatch.setattr(playwright_utils, 'reap_leaked_browsers', explode, raising=False)

    inst = ds.DeploymentScheduler.__new__(ds.DeploymentScheduler)
    inst.host_name = 'h'
    inst._reap_leaked_browsers()  # must not raise