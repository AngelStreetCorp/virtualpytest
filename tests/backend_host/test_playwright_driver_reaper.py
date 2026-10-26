"""The reclaim pass must see an orphaned Playwright driver (BUG-0842).

A Playwright driver is the Node process ``async_playwright().start()`` spawns. It holds no
port of its own, so every port-based count on the host was blind to it: a run that wedged
left its driver behind for ever (a leaked ~74 MB per hung run), while the browser it held
was reclaimed by the port pass and the driver was not.

The rule is the port scan's rule asked of the driver instead of the port: a driver holds
the browser it drives through the CDP connection it opened to that browser's debug port,
so a driver whose connection is gone is holding nothing and belongs to no live run. The
driver of a run in progress still holds its browser, and the port registry names the run
that owns it — so it is never touched.

What is checked here:
  - an orphaned driver is reaped,
  - the driver of a live run is not,
  - a driver that has just started is not mistaken for an orphan,
  - the match is on argv entries, never on a substring of a command line,
  - the reaper signals individual pids, never a process group.
"""

import os
import types

import pytest

from shared.src.lib.utils import leaked_browser_reaper as reaper


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _all_code_objects(func):
    seen, stack = [], [func.__code__]
    while stack:
        code = stack.pop()
        seen.append(code)
        stack.extend(c for c in code.co_consts if isinstance(c, types.CodeType))
    return seen


DRIVER_ARGV = ['/usr/bin/node',
               '/opt/virtualpytest/venv/lib/python3.11/site-packages/playwright/driver/package/cli.js',
               'run-driver']


def _driver_host(monkeypatch, pid, argv, ports, owner_pid, age=3600.0):
    """A host with one driver, the browser it holds and the run that owns that browser."""
    assert hasattr(reaper, '_process_age_seconds'), \
        'the reclaim pass cannot tell a driver from an orphan'
    monkeypatch.setattr(reaper, '_all_pids', lambda: [pid])
    monkeypatch.setattr(reaper, '_argv', lambda p: argv)
    monkeypatch.setattr(reaper, '_process_age_seconds', lambda p: age)
    monkeypatch.setattr(reaper, 'driver_browser_ports', lambda p: ports)
    monkeypatch.setattr(
        'shared.src.lib.utils.browser_port_allocator.port_owner_pid',
        lambda port, *a, **k: owner_pid)


# ---------------------------------------------------------------------------
# Discovery: an argv ENTRY, and a process that is really a driver
# ---------------------------------------------------------------------------

def test_a_real_driver_is_found():
    assert reaper._is_playwright_driver(DRIVER_ARGV) is True


def test_a_command_line_that_merely_mentions_the_driver_is_not_a_driver():
    """A wrapper carries the whole script in ONE argv entry, so a substring search finds it."""
    wrapper = ['/bin/bash', '-c', 'node .../playwright/driver/package/cli.js run-driver']
    assert reaper._is_playwright_driver(wrapper) is False


def test_a_process_that_is_not_a_driver_is_not_a_driver():
    assert reaper._is_playwright_driver(['/usr/bin/node', '/opt/app/server.js']) is False
    assert reaper._is_playwright_driver([]) is False


# ---------------------------------------------------------------------------
# The reclaim: an orphan goes, a live run's driver stays
# ---------------------------------------------------------------------------

def test_an_orphaned_driver_is_reaped(monkeypatch):
    """Its browser is gone: it holds nothing and belongs to no live run."""
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[], owner_pid=None)

    signalled = []
    monkeypatch.setattr(reaper, 'reap_browser_tree',
                        lambda pid, run_root, grace_seconds=5.0: (
                            signalled.append(pid) or
                            {'signalled': [pid], 'killed': [], 'skipped': ''}))

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['reaped'], 'the orphaned driver was left running'
    assert out['reaped'][0]['pid'] == 4242
    assert signalled == [4242]


def test_the_driver_of_a_live_run_is_not_reaped(monkeypatch):
    """It still holds the browser its run owns: a live run is never torn down."""
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[9300], owner_pid=777)

    monkeypatch.setattr(reaper, 'reap_browser_tree',
                        lambda *a, **k: pytest.fail('a live run must never be torn down'))

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['reaped'] == []


def test_a_driver_whose_browser_belongs_to_no_run_is_reaped(monkeypatch):
    """The browser is still there but no live run owns it: the run is over."""
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[9300], owner_pid=None)

    monkeypatch.setattr(reaper, 'reap_browser_tree',
                        lambda pid, run_root, grace_seconds=5.0: (
                            {'signalled': [pid], 'killed': [], 'skipped': ''}))

    out = reaper.reap_orphaned_drivers(grace_seconds=0)

    assert out['reaped']
    assert out['reaped'][0]['pid'] == 4242


def test_a_driver_that_has_just_started_is_not_an_orphan(monkeypatch):
    """It may not have opened its CDP connection yet."""
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[], owner_pid=None, age=1.0)

    monkeypatch.setattr(reaper, 'reap_browser_tree',
                        lambda *a, **k: pytest.fail('a driver that just started was killed'))

    out = reaper.reap_orphaned_drivers(grace_seconds=0, min_age_seconds=60.0)

    assert out['reaped'] == []


def test_a_dry_run_reports_but_signals_nothing(monkeypatch):
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[], owner_pid=None)

    monkeypatch.setattr(reaper, 'reap_browser_tree',
                        lambda *a, **k: pytest.fail('must not kill'))

    out = reaper.reap_orphaned_drivers(dry_run=True, grace_seconds=0)

    assert out['reaped'] == []
    assert out['skipped'][0]['reason'] == 'dry run'


# ---------------------------------------------------------------------------
# The hard safety property: never a process group
# ---------------------------------------------------------------------------

def test_the_driver_reaper_never_references_a_group_signal():
    banned = ('killpg', 'setsid', 'getpgid', 'setpgid', 'os.getpgrp')
    for func in (reaper.reap_orphaned_drivers, reaper.orphaned_driver_pids,
                 reaper.reap_browser_tree):
        for code in _all_code_objects(func):
            for name in banned:
                assert name not in code.co_names, f'{func.__name__} references {name}'


def test_the_driver_reaper_signals_only_positive_pids(monkeypatch):
    import shared.src.lib.utils.leaked_browser_reaper as mod
    _driver_host(monkeypatch, 4242, DRIVER_ARGV, ports=[], owner_pid=None)
    monkeypatch.setattr(mod, 'descendants_of', lambda pid: [])

    seen = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: seen.append((pid, sig)))
    monkeypatch.setattr(os.path, 'exists', lambda p: False)

    mod.reap_browser_tree(4242, '', grace_seconds=0)

    assert seen, 'nothing was signalled at all'
    for pid, _sig in seen:
        assert pid > 0, f'{pid} is a process GROUP (negative pid), not a process'


# ---------------------------------------------------------------------------
# The reclaim pass runs the driver half too
# ---------------------------------------------------------------------------

def test_the_reclaim_pass_reclaims_orphaned_drivers(monkeypatch):
    """The port scan cannot see a driver, so the reclaim pass has to ask for it explicitly."""
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: ())
    monkeypatch.setattr(reaper, 'reap_orphaned_drivers',
                        lambda **k: {'reaped': [{'pid': 4242}], 'skipped': []})

    out = reaper.reap_leaked_browsers(run_root='/runs')

    assert out['reaped_drivers'] == [{'pid': 4242}]
