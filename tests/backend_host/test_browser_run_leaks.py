"""
tests/backend_host/test_browser_run_leaks.py — the cap counts what the host carries, not what
it believes it started (BUG-0760).

A run gives its slot back when it ends whether or not its browser died. A Chromium that
outlives its run was therefore invisible: the host reported `running: 0` while carrying nine
of them, ~2 GB of a 3.9 GB host, one leaked per hour. The cap was advisory rather than a limit.

What is checked here:
  - a listener on a run port whose owner is gone counts as leaked,
  - a listener whose owner is ALIVE is a run in flight and is not double-counted,
  - a free port is not a leak,
  - a leak counts against the cap, so a host carrying dead browsers admits nothing more,
  - a failing measurement degrades to the old behaviour instead of blocking runs,
  - and nothing here kills anything: the scan is read-only, deliberately.
"""
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

slots = importlib.import_module('shared.src.lib.utils.browser_run_slots')
allocator = importlib.import_module('shared.src.lib.utils.browser_port_allocator')


@pytest.fixture(autouse=True)
def private_registry(tmp_path, monkeypatch):
    """Never touch the host's real port registry, and never reuse its cache."""
    monkeypatch.setenv(allocator.REGISTRY_ENV, str(tmp_path / 'registry'))
    (tmp_path / 'registry').mkdir(exist_ok=True)
    slots._leak_cache.update({'at': 0.0, 'ports': ()})
    monkeypatch.setattr(slots, 'LEAK_SCAN_SPAN', 8)
    yield


@pytest.fixture
def host(monkeypatch):
    """A fake host: `listening` ports, and which of them a live run owns."""
    state = {'listening': set(), 'owned': {}}

    monkeypatch.setattr(allocator, 'is_port_listening', lambda port, *a, **k: port in state['listening'])
    monkeypatch.setattr(allocator, 'port_owner_pid', lambda port, *a, **k: state['owned'].get(port))
    return state


def _forget_cache():
    slots._leak_cache.update({'at': 0.0, 'ports': ()})


# ── the measurement ──────────────────────────────────────────────────────────────

def test_a_listener_with_no_live_owner_is_leaked(host):
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base, base + 1}
    _forget_cache()

    assert slots.leaked_browser_ports() == (base, base + 1)


def test_a_listener_whose_run_is_alive_is_not_leaked(host):
    """It is a run in flight — already counted by the pool, so counting it again would
    make the cap stricter than the host actually is."""
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base}
    host['owned'] = {base: 4242}
    _forget_cache()

    assert slots.leaked_browser_count() == 0


def test_a_free_port_is_not_a_leak(host):
    _forget_cache()

    assert slots.leaked_browser_count() == 0


def test_the_scan_is_cached(host):
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base}
    _forget_cache()

    assert slots.leaked_browser_count() == 1

    # The browser dies, but the cached answer stands for a few seconds: the dashboard
    # asks on every read and must not pay for a sweep each time.
    host['listening'].clear()
    assert slots.leaked_browser_count() == 1

    _forget_cache()
    assert slots.leaked_browser_count() == 0


def test_a_broken_measurement_degrades_instead_of_blocking(monkeypatch):
    """A host we cannot measure must fall back to counting runs, not wedge."""
    def boom(*_a, **_k):
        raise OSError("no /proc")

    monkeypatch.setattr(allocator, 'is_port_listening', boom)
    _forget_cache()

    assert slots.leaked_browser_count() == 0


def test_the_scan_never_kills_anything(monkeypatch):
    """The whole point of the caution in BUG-0760, asserted.

    Signalling a browser's process group without checking what else shares it took a lab
    host's SSH down on 2026-10-22. This scan exists so nobody has to reap blindly.
    """
    # co_names is the set of global/attribute names the function body actually
    # references — immune to the wording of its own docstring, which discusses killing.
    referenced = set(slots.leaked_browser_ports.__code__.co_names)

    for forbidden in ('kill', 'killpg', 'shutdown_chrome', 'popen', 'run', 'system', 'Popen'):
        assert not any(forbidden in name for name in referenced), (
            f"leaked_browser_ports must not reference {forbidden!r}; it found {sorted(referenced)}")


# ── the cap counts them ──────────────────────────────────────────────────────────

def test_leaks_count_against_the_cap(monkeypatch, host):
    """A host carrying more dead browsers than its cap admits nothing."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '2')
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base, base + 1}
    _forget_cache()

    result = slots.BrowserSlotPool().acquire(timeout=0)

    assert result['ok'] is False
    assert result['leaked'] == 2
    assert 'left over from finished runs' in result['error']


def test_room_beside_a_leak_is_still_handed_out(monkeypatch, host):
    """One dead browser and a cap of two: a real run may still start."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '2')
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base}
    _forget_cache()

    result = slots.BrowserSlotPool().acquire(timeout=0)

    assert result['ok'] is True
    assert result['leaked'] == 1


def test_a_full_host_still_says_the_old_thing_when_nothing_leaked(monkeypatch, host):
    """No leaks, no change to the message an operator already knows."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '1')
    pool = slots.BrowserSlotPool()
    pool._running = 1
    _forget_cache()

    result = pool.acquire(timeout=0)

    assert result['ok'] is False
    assert 'already runs 1 browser test(s)' in result['error']


def test_status_reports_the_leaks(monkeypatch, host):
    """The host card has to show the load the old count missed."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '4')
    base = allocator.RUN_DEBUG_PORT_BASE
    host['listening'] = {base, base + 2}
    _forget_cache()

    status = slots.BrowserSlotPool().status()

    assert status['leaked'] == 2
    assert status['running'] == 0
    assert status['cap'] == 4