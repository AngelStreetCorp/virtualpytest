"""The reclaim pass (BUG-0760 part 1): what it may kill, and what it must never touch.

The bar here is not "does it clean up" but "can it ever take down something it should not".
Signalling a Chromium's process *group* took host-clone-2's SSH down on 2026-10-22, so the
group-safety assertions below are structural, not behavioural: they read the function's own
code object.
"""
import os
import signal
import sys
import types

import pytest

from shared.src.lib.utils import leaked_browser_reaper as reaper


# ---------------------------------------------------------------------------
# The hard safety property: never a process group, ever a negative pid
# ---------------------------------------------------------------------------

def _all_code_objects(func):
    seen, stack = [], [func.__code__]
    while stack:
        code = stack.pop()
        seen.append(code)
        stack.extend(c for c in code.co_consts if isinstance(c, types.CodeType))
    return seen


def test_the_reaper_never_references_a_group_signal():
    """No killpg, no negative pid, no setsid/PGID arithmetic anywhere in the module."""
    banned = ('killpg', 'setsid', 'getpgid', 'setpgid', 'os.getpgrp')
    for func in (reaper.reap_browser_tree, reaper.reap_leaked_browsers, reaper.descendants_of):
        for code in _all_code_objects(func):
            for name in banned:
                assert name not in code.co_names, f'{func.__name__} references {name}'


def test_the_reaper_signals_only_positive_pids(monkeypatch):
    """Whatever it signals, every pid handed to os.kill is > 0. A group is a negative pid."""
    import shared.src.lib.utils.leaked_browser_reaper as mod
    monkeypatch.setattr(mod, 'descendants_of', lambda pid: [pid + 1])
    monkeypatch.setattr(os.path, 'exists', lambda p: False)

    seen = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: seen.append((pid, sig)))

    mod.reap_browser_tree(4242, '/runs', grace_seconds=0)

    assert seen, 'nothing was signalled at all'
    for pid, _sig in seen:
        assert pid > 0, f'{pid} is a process GROUP (negative pid), not a process'


def test_a_tree_is_taken_down_children_before_parent(monkeypatch):
    import shared.src.lib.utils.leaked_browser_reaper as mod
    monkeypatch.setattr(mod, 'descendants_of', lambda pid: [pid + 1, pid + 2])
    monkeypatch.setattr(os.path, 'exists', lambda p: False)

    order = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: order.append(pid))

    mod.reap_browser_tree(1000, '/runs', grace_seconds=0)

    assert order[0] != 1000, 'the browser outlived its renderers'


# ---------------------------------------------------------------------------
# Discovery: an argv ENTRY, and a process that is actually a browser
# ---------------------------------------------------------------------------

def test_discovery_ignores_a_command_line_that_merely_mentions_the_flag(monkeypatch):
    """Found live on host-clone-2: the reaper matched an ssh/python wrapper, not the browser.

    The wrapper carries the whole script in ONE argv entry, so a substring search finds the flag
    inside it. Had that wrapper carried a run-scoped profile, we would have signalled a shell.
    """
    wrapper = 4242
    script = ('import time; time.sleep(300) --remote-debugging-port=9397 '
              '--user-data-dir=/runs/livetest')
    monkeypatch.setattr(reaper, '_all_pids', lambda: [wrapper])
    # one argv entry containing the text - exactly what a `bash -c "..."` looks like
    monkeypatch.setattr(reaper, '_argv', lambda pid: ['/bin/bash', '-c', script])

    assert reaper.browser_pid_for_port(9397) is None


def test_discovery_finds_a_real_browser(monkeypatch):
    monkeypatch.setattr(reaper, '_all_pids', lambda: [900, 901])
    monkeypatch.setattr(reaper, '_argv', lambda pid: {
        900: ['/bin/bash', '-c', 'python stuff --remote-debugging-port=9397'],
        901: ['/usr/lib/chromium/chromium', '--remote-debugging-port=9397',
              '--user-data-dir=/runs/run-1'],
    }[pid])

    assert reaper.browser_pid_for_port(9397) == 901


def test_a_non_browser_on_the_port_is_not_a_browser(monkeypatch):
    """Same flags, wrong executable: refused."""
    monkeypatch.setattr(reaper, '_all_pids', lambda: [902])
    monkeypatch.setattr(reaper, '_argv', lambda pid: [
        '/usr/bin/python3', '-c', 'x', '--remote-debugging-port=9397', '--user-data-dir=/runs/run-1'])

    assert reaper.browser_pid_for_port(9397) is None


def test_the_user_data_dir_is_read_from_argv_not_whitespace(monkeypatch):
    """A quoted flag inside a script is not a --user-data-dir the process was launched with."""
    monkeypatch.setattr(reaper, '_argv', lambda pid: ['/bin/bash', '-c', 'x "--user-data-dir=/runs/r"'])
    assert reaper._user_data_dir(4242) is None
    monkeypatch.setattr(reaper, '_argv', lambda pid: ['/usr/lib/chromium/chromium', '--user-data-dir=/runs/r'])
    assert reaper._user_data_dir(4242) == '/runs/r'


# ---------------------------------------------------------------------------
# The run root is found, never counted
# ---------------------------------------------------------------------------

def test_the_run_root_is_the_one_the_allocator_actually_uses():
    """A wrong run root makes the guard refuse every real browser, so the reaper reaps nothing.

    Found live on the deployed host: counting dirname levels produced
    ``<root>/shared/backend_host/config/user_data_runs`` instead of
    ``<root>/backend_host/config/user_data_runs``.
    """
    root = reaper.default_run_profile_root()
    assert root.endswith(os.path.join('backend_host', 'config', 'user_data_runs')), root
    assert f'{os.sep}shared{os.sep}backend_host' not in root, root
    assert os.path.isdir(os.path.dirname(root)), f'{root} is not next to the real config dir'


def test_the_run_root_is_inside_this_checkout():
    """It must resolve to THIS repo, not to a hard-coded path."""
    root = os.path.abspath(reaper.default_run_profile_root())
    here = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    assert root.startswith(here), f'{root} is not under {here}'


def test_a_real_run_profile_directory_would_be_accepted(tmp_path):
    """The guard is checked against a path shaped like the allocator's output."""
    base = tmp_path / 'backend_host' / 'config' / 'user_data'
    base.mkdir(parents=True)
    run_root = os.path.join(str(tmp_path), 'backend_host', 'config', 'user_data_runs')
    profile = os.path.join(run_root, 'some-run-id')
    assert reaper._is_run_scoped(profile, run_root)
    assert not reaper._is_run_scoped(str(base), run_root)


# ---------------------------------------------------------------------------
# The profile guard: only the allocator's per-run directory
# ---------------------------------------------------------------------------

def test_a_run_scoped_profile_is_recognised(tmp_path):
    run_root = str(tmp_path / 'user_data_runs')
    assert reaper._is_run_scoped(os.path.join(run_root, 'run-1'), run_root)


def test_the_hosts_own_persistent_profile_is_never_a_run_profile(tmp_path):
    """The service browser and the display browser live next door and must be off limits."""
    base = tmp_path / 'config' / 'user_data'
    base.mkdir(parents=True)
    assert not reaper._is_run_scoped(str(base), str(tmp_path / 'config' / 'user_data_runs'))


def test_a_sibling_directory_with_a_shared_prefix_is_not_a_run_profile(tmp_path):
    """'user_data_runs_backup' must not pass as 'user_data_runs'."""
    run_root = str(tmp_path / 'user_data_runs')
    assert not reaper._is_run_scoped(str(tmp_path / 'user_data_runs_backup' / 'run-1'), run_root)


def test_a_browser_with_no_user_data_dir_is_never_reaped(tmp_path):
    assert not reaper._is_run_scoped(None, str(tmp_path / 'user_data_runs'))


# ---------------------------------------------------------------------------
# The owner guard: a run in progress is never reaped
# ---------------------------------------------------------------------------

def test_a_port_a_live_run_owns_is_skipped(monkeypatch):
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: (9300,))
    monkeypatch.setattr('shared.src.lib.utils.browser_port_allocator.port_owner_pid', lambda port: 777)
    monkeypatch.setattr(reaper, 'browser_pid_for_port', lambda port: 888)

    out = reaper.reap_leaked_browsers(run_root='/runs')

    assert out['reaped'] == []
    assert 'live run' in out['skipped'][0]['reason']


def test_a_browser_whose_profile_is_not_a_run_profile_is_skipped(monkeypatch):
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: (9300,))
    monkeypatch.setattr('shared.src.lib.utils.browser_port_allocator.port_owner_pid', lambda port: None)
    monkeypatch.setattr(reaper, 'browser_pid_for_port', lambda port: 888)
    monkeypatch.setattr(reaper, '_user_data_dir', lambda pid: '/opt/vpt/config/user_data')
    monkeypatch.setattr(reaper, 'reap_browser_tree', lambda *a, **k: pytest.fail('must not kill'))

    out = reaper.reap_leaked_browsers(run_root='/opt/vpt/backend_host/config/user_data_runs')

    assert out['reaped'] == []
    assert out['skipped'][0]['reason'] == 'profile is not a per-run profile'


def test_the_reaper_refuses_to_signal_itself_or_its_parent():
    me = os.getpid()
    out = reaper.reap_browser_tree(me, '/runs', grace_seconds=0)
    assert out['signalled'] == []
    assert 'this process' in out['skipped']


# ---------------------------------------------------------------------------
# The off switch and the dry run
# ---------------------------------------------------------------------------

def test_the_off_switch_touches_nothing(monkeypatch):
    monkeypatch.setenv('VPT_REAP_LEAKED_BROWSERS', 'false')
    monkeypatch.setattr(reaper, 'reap_browser_tree', lambda *a, **k: pytest.fail('must not kill'))
    out = reaper.reap_leaked_browsers()
    assert out['enabled'] is False
    assert out['reaped'] == []


def test_reaping_is_on_by_default(monkeypatch):
    monkeypatch.delenv('VPT_REAP_LEAKED_BROWSERS', raising=False)
    assert reaper.reaping_enabled() is True


def test_a_dry_run_reports_but_signals_nothing(monkeypatch):
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: (9300,))
    monkeypatch.setattr('shared.src.lib.utils.browser_port_allocator.port_owner_pid', lambda port: None)
    monkeypatch.setattr(reaper, 'browser_pid_for_port', lambda port: 888)
    monkeypatch.setattr(reaper, '_user_data_dir', lambda pid: '/runs/run-1')
    monkeypatch.setattr(reaper, 'reap_browser_tree', lambda *a, **k: pytest.fail('must not kill'))

    out = reaper.reap_leaked_browsers(dry_run=True, run_root='/runs')

    assert out['reaped'] == []
    assert out['skipped'][0]['reason'] == 'dry run'


def test_a_dead_run_browser_is_reaped_and_the_cache_is_invalidated(monkeypatch):
    monkeypatch.setattr(reaper, 'reaping_enabled', lambda: True)
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.leaked_browser_ports', lambda: (9300,))
    monkeypatch.setattr('shared.src.lib.utils.browser_port_allocator.port_owner_pid', lambda port: None)
    monkeypatch.setattr(reaper, 'browser_pid_for_port', lambda port: 888)
    monkeypatch.setattr(reaper, '_user_data_dir', lambda pid: '/runs/run-1')
    monkeypatch.setattr(reaper, 'reap_browser_tree', lambda *a, **k: {'signalled': [888, 889], 'killed': []})

    invalidated = []
    monkeypatch.setattr('shared.src.lib.utils.browser_run_slots.invalidate_leak_cache',
                        lambda: invalidated.append(True))

    out = reaper.reap_leaked_browsers(run_root='/runs')

    assert out['reaped'][0]['port'] == 9300
    assert invalidated, 'a stale leak cache would keep counting a browser that is gone'


# ---------------------------------------------------------------------------
# The pool only pays for this when the host is actually full
# ---------------------------------------------------------------------------

def test_a_healthy_host_is_admitted_without_ever_reaping(monkeypatch):
    """leaked=0, cap=4: the run must not pay for a reclaim pass it does not need."""
    from shared.src.lib.utils import browser_run_slots as slots
    monkeypatch.setattr(slots, 'leaked_browser_count', lambda: 0)
    monkeypatch.setattr(slots, 'max_parallel_browser_runs', lambda: 4)
    monkeypatch.setattr(
        'shared.src.lib.utils.leaked_browser_reaper.reap_leaked_browsers',
        lambda **k: pytest.fail('a host with no leaks must not trigger a reap'))

    got = slots.BrowserSlotPool().acquire(timeout=0)
    assert got['ok'] is True


def test_a_host_wedged_by_leaks_reclaims_and_then_admits(monkeypatch):
    """This is the half that was missing: full + leaks used to mean refusal for ever."""
    from shared.src.lib.utils import browser_run_slots as slots
    monkeypatch.setattr(slots, 'max_parallel_browser_runs', lambda: 4)

    counts = iter([5, 5, 0])
    monkeypatch.setattr(slots, 'leaked_browser_count', lambda: next(counts, 0))

    calls = []

    def fake_reap(**kwargs):
        calls.append(kwargs)
        return {'reaped': [{'port': 9300, 'pid': 888}], 'skipped': []}

    monkeypatch.setattr('shared.src.lib.utils.leaked_browser_reaper.reap_leaked_browsers', fake_reap)

    got = slots.BrowserSlotPool().acquire(timeout=5)

    assert calls, 'a full host with leaks never attempted a reclaim'
    assert got['ok'] is True, 'the run was refused even though the reclaim freed the host'
    assert got['running'] == 1


def test_a_reap_failure_does_not_fail_the_run(monkeypatch):
    """A reap that blows up must degrade to the old behaviour, never to a failed run."""
    from shared.src.lib.utils import browser_run_slots as slots
    monkeypatch.setattr(slots, 'max_parallel_browser_runs', lambda: 1)
    monkeypatch.setattr(slots, 'leaked_browser_count', lambda: 1)

    def boom(**kwargs):
        raise RuntimeError('reap exploded')

    monkeypatch.setattr('shared.src.lib.utils.leaked_browser_reaper.reap_leaked_browsers', boom)

    got = slots.BrowserSlotPool().acquire(timeout=0)

    assert got['ok'] is False
    assert 'reap exploded' not in got['error']
    assert 'left over' in got['error']


# ---------------------------------------------------------------------------
# The declaration that lets the cap see this script at all
# ---------------------------------------------------------------------------

def test_game_tetris_declares_itself_browser_isolated():
    """Without the flag this script takes no browser slot and the cap is blind to it."""
    from shared.src.lib.utils.script_target_rules_utils import extract_script_target_rules_from_path
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, 'test_scripts', 'game', 'game_tetris.py')
    rules = extract_script_target_rules_from_path(path)
    assert rules.get('browser_isolated') is True