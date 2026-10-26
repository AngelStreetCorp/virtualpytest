"""The driver reaper must report what it actually did (BUG-0842 follow-up).

Found live on the deployed host on 2026-10-24: the reaper found a real orphaned
Playwright driver and logged

    [leaked_browser_reaper] driver 1442790: its browser is gone, took down 0 process(es)
    [reap_leaked_browsers] reclaimed orphaned Playwright driver(s): [1442790]

and the driver was still running a minute later. The reaper had **not** signalled it:
``os.kill`` raised ``PermissionError`` (the driver belongs to another user),
``PermissionError`` is an ``OSError``, and the signal loop caught it as one and dropped
the reason. So ``signalled`` came back empty, "took down 0 process(es)" was read as a
success, and the driver was written into the list of reclaimed drivers.

That is BUG-0089's shape again - a run that never happened recorded as successful -
inside the very fix for a bug about runs that never report. The reaper is the thing that
tells the truth about what it did, so:

  - a driver the reaper cannot signal is **skipped with its reason**, never reclaimed;
  - a driver that is already gone is reported as gone, not as a permission failure;
  - the "reclaimed" line names only the drivers that were really taken down.

The safety rules are untouched: a driver holding a browser a live run owns is never a
candidate, individual positive pids only, never a process group, and the reaper's own
process and its parent are never signalled. This is about **reporting**, not about
killing more: no escalation, no wider net, no sudo.
"""

import os

import pytest

from shared.src.lib.utils import leaked_browser_reaper as reaper


# A pid that cannot exist (the kernel's pid_max is far below it), so nothing in this
# file can ever signal a real process, whatever the test does.
FAKE_PID = 987654321

# Obviously fake paths: the driver is recognised by its argv ENTRIES ('run-driver' plus a
# path containing 'playwright'), not by anything host-specific.
DRIVER_ARGV = ['/usr/bin/node',
               '/opt/example/site-packages/playwright/driver/package/cli.js',
               'run-driver']


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _driver_host(monkeypatch, pid=FAKE_PID, ports=(), owner_pid=None, age=3600.0):
    """A host with exactly one Playwright driver on it and nothing else."""
    monkeypatch.setattr(reaper, '_all_pids', lambda: [pid])
    monkeypatch.setattr(reaper, '_argv', lambda p: DRIVER_ARGV)
    monkeypatch.setattr(reaper, '_process_age_seconds', lambda p: age)
    monkeypatch.setattr(reaper, 'driver_browser_ports', lambda p: list(ports))
    monkeypatch.setattr(
        'shared.src.lib.utils.browser_port_allocator.port_owner_pid',
        lambda port, *a, **k: owner_pid)


def _signal_fails(monkeypatch, error):
    """os.kill that fails the way the kernel refuses a process of another user.

    The real os.kill is never reached, so no process is signalled by this file.
    """
    def fake_kill(target, sig):
        if target == FAKE_PID:
            raise error
    monkeypatch.setattr(os, 'kill', fake_kill)


# ---------------------------------------------------------------------------
# The refusal must be reported, not swallowed
# ---------------------------------------------------------------------------

def test_a_refused_signal_is_reported_with_its_cause(monkeypatch):
    """PermissionError used to be caught as a plain OSError, so the reason was thrown away."""
    monkeypatch.setattr(reaper, 'descendants_of', lambda pid: [])
    _signal_fails(monkeypatch, PermissionError(1, 'Operation not permitted'))

    outcome = reaper.reap_browser_tree(FAKE_PID, '', grace_seconds=0)

    assert outcome['signalled'] == [], 'a refused signal was counted as one that landed'
    assert outcome['failed'], 'the refusal was thrown away instead of reported'
    assert outcome['failed'][0]['pid'] == FAKE_PID
    assert 'permission denied' in outcome['failed'][0]['error']
    # the keys the callers read are still there
    assert outcome['pid'] == FAKE_PID
    assert outcome['killed'] == []


def test_a_driver_the_reaper_cannot_signal_is_not_reclaimed(monkeypatch, capsys):
    """The defect the manager saw live: a driver nobody could signal, reported as reclaimed."""
    _driver_host(monkeypatch)
    _signal_fails(monkeypatch, PermissionError(1, 'Operation not permitted'))

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['reaped'] == [], 'a driver nobody could signal was reported as reclaimed'
    assert out['skipped'], 'the driver that survived was not reported at all'
    assert 'permission denied' in out['skipped'][0]['reason']

    printed = capsys.readouterr().out
    announced = [line for line in printed.splitlines() if 'reclaimed' in line]
    assert not announced, f'a driver that was not reclaimed was announced: {announced}'
    assert 'NOT reaped' in printed


def test_the_reclaimed_line_names_only_the_drivers_really_taken_down(monkeypatch, capsys):
    """This is the line the manager read on the host."""
    from backend_host.src.lib.utils import playwright_utils
    import shared.src.lib.utils.browser_run_slots as slots

    monkeypatch.setenv('VPT_REAP_LEAKED_BROWSERS', '1')
    monkeypatch.setattr(slots, 'leaked_browser_ports', lambda: ())
    _driver_host(monkeypatch)
    _signal_fails(monkeypatch, PermissionError(1, 'Operation not permitted'))

    playwright_utils.reap_leaked_browsers()

    printed = capsys.readouterr().out
    announced = [line for line in printed.splitlines()
                 if 'reclaimed orphaned Playwright driver(s)' in line]
    assert not announced, f'a driver that was not reclaimed was announced: {announced}'
    assert 'NOT reaped' in printed
    assert 'permission denied' in printed


def test_the_browser_half_does_not_report_a_refused_signal_as_a_reclaim(monkeypatch, capsys):
    """The same lie in the other half of the same module: nothing signalled, nothing reclaimed."""
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: (9300,))
    monkeypatch.setattr('shared.src.lib.utils.browser_port_allocator.port_owner_pid', lambda port: None)
    monkeypatch.setattr(reaper, 'browser_pid_for_port', lambda port: FAKE_PID)
    monkeypatch.setattr(reaper, '_user_data_dir', lambda pid: '/runs/run-1')
    monkeypatch.setattr(reaper, 'descendants_of', lambda pid: [])
    monkeypatch.setattr(reaper, 'reap_orphaned_drivers',
                        lambda **k: {'reaped': [], 'skipped': []})
    _signal_fails(monkeypatch, PermissionError(1, 'Operation not permitted'))

    out = reaper.reap_leaked_browsers(run_root='/runs')

    assert out['reaped'] == [], 'a browser nobody could signal was reported as reclaimed'
    assert 'permission denied' in out['skipped'][0]['reason']
    printed = capsys.readouterr().out
    assert 'reclaimed 1 browser(s)' not in printed, 'a reclaim that never happened was announced'


# ---------------------------------------------------------------------------
# "Already gone" is not a failure
# ---------------------------------------------------------------------------

def test_a_driver_that_is_already_gone_is_reported_as_gone_and_not_as_a_failure(monkeypatch, capsys):
    """ESRCH means the goal is met: the driver is not there any more."""
    _driver_host(monkeypatch)
    _signal_fails(monkeypatch, ProcessLookupError(3, 'No such process'))

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['skipped'] == [], 'a driver that was already gone was counted as a failure'
    assert out['reaped'], 'a driver that is gone is not a leak any more'
    assert out['reaped'][0].get('already_gone') is True

    printed = capsys.readouterr().out
    assert 'permission denied' not in printed
    assert 'took down 0 process(es)' not in printed, \
        'a reclaim that took nothing down was announced as one'


# ---------------------------------------------------------------------------
# The early return is a skip, never a reclaim
# ---------------------------------------------------------------------------

def test_the_reaper_never_reports_its_own_process_as_reclaimed(monkeypatch):
    """The early return ('this process or its parent') is a skip, not a reclaim."""
    monkeypatch.setattr(
        reaper, 'orphaned_driver_pids',
        lambda min_age_seconds=60.0: [{'pid': os.getpid(), 'ports': [],
                                        'reason': 'its browser is gone'}])

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['reaped'] == [], 'the reaper reported a reclaim it never performed'
    assert out['skipped'][0]['reason'] == 'this process or its parent'
