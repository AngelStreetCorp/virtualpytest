"""How many browser test runs one host carries at the same time (TASK-146).

Browser-isolated web scripts each drive a Chrome of their own (their own debug port and
their own profile), so several of them share one host instead of queueing behind each
other. That makes the HOST the scarce resource: each run is a Chromium with a profile of
its own, and the host's RAM and CPU are finite.

So the host caps them: at most VPT_MAX_PARALLEL_BROWSER_RUNS (6 by default) browser runs
at the same time. A run that finds the host full waits for a free slot instead of piling
on - and the wait never blocks the caller, because the host starts scripts in a background
thread.
"""
import importlib
import os
import threading
import time

import pytest

slots_mod = importlib.import_module('shared.src.lib.utils.browser_run_slots')
BrowserSlotPool = slots_mod.BrowserSlotPool
executor_mod = importlib.import_module('shared.src.lib.executors.script_executor')


@pytest.fixture(autouse=True)
def no_leaked_browsers_here(monkeypatch):
    """These tests are about the POOL, so they control what the pool measures.

    `acquire()` now counts the browsers the host is CARRYING, not only the ones this pool
    started (BUG-0760). That measurement is a real sweep of the run ports, so without
    this every test below would depend on what happens to be listening on the machine
    running it -- which is how "2 browser(s) left over from finished runs" ends up in a
    unit test. The measurement itself is covered by test_browser_run_leaks.py.
    """
    monkeypatch.setattr(slots_mod, 'leaked_browser_count', lambda: 0)


# ---------------------------------------------------------------------------
# The cap itself
# ---------------------------------------------------------------------------

def test_the_cap_follows_the_hosts_memory(monkeypatch):
    """Six Chromes on a 4 GB box would thrash it: the cap follows the memory."""
    monkeypatch.delenv('VPT_MAX_PARALLEL_BROWSER_RUNS', raising=False)

    monkeypatch.setattr(slots_mod, '_total_memory_mb', lambda: 3915)  # the lab's smallest
    assert slots_mod.max_parallel_browser_runs() == 4

    monkeypatch.setattr(slots_mod, '_total_memory_mb', lambda: 16384)
    assert slots_mod.max_parallel_browser_runs() == 6  # never more than the maximum

    monkeypatch.setattr(slots_mod, '_total_memory_mb', lambda: 2048)
    assert slots_mod.max_parallel_browser_runs() == 1  # a small host carries one


def test_a_host_that_cannot_be_asked_gets_the_maximum(monkeypatch):
    monkeypatch.delenv('VPT_MAX_PARALLEL_BROWSER_RUNS', raising=False)
    monkeypatch.setattr(slots_mod, '_total_memory_mb', lambda: None)
    assert slots_mod.max_parallel_browser_runs() == 6


def test_the_cap_is_configurable(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '3')
    assert slots_mod.max_parallel_browser_runs() == 3


def test_a_broken_cap_falls_back_to_the_memory_rule(monkeypatch):
    monkeypatch.setattr(slots_mod, '_total_memory_mb', lambda: 3915)
    for value in ('', 'many', '0', '-2'):
        monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', value)
        assert slots_mod.max_parallel_browser_runs() == 4


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------

def test_a_free_slot_is_handed_out(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    result = pool.acquire(timeout=0)
    assert result['ok'] is True
    assert result['running'] == 1
    assert result['cap'] == 6
    assert pool.status()['running'] == 1


def test_the_pool_fills_up_to_the_cap(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '2')
    pool = BrowserSlotPool()
    assert pool.acquire(timeout=0)['ok'] is True
    assert pool.acquire(timeout=0)['ok'] is True
    third = pool.acquire(timeout=0)
    assert third['ok'] is False
    assert third['running'] == 2
    assert third['cap'] == 2


def test_a_run_waits_for_a_free_slot_and_gets_it(monkeypatch):
    """The host is full: the run waits, and the slot goes to it as soon as one frees."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    for _ in range(6):  # every slot taken
        pool.acquire(timeout=0)

    got = {}

    def wait_for_slot():
        got['result'] = pool.acquire(timeout=5)

    waiter = threading.Thread(target=wait_for_slot, daemon=True)
    waiter.start()
    time.sleep(0.2)
    assert waiter.is_alive(), "the run should be waiting for a free slot"
    assert pool.status()['waiting'] == 1

    pool.release()  # the running browser finished
    waiter.join(timeout=5)
    assert not waiter.is_alive()
    assert got['result']['ok'] is True
    assert got['result']['running'] == 6, "the freed slot went to the waiting run"


def test_a_wait_that_runs_out_refuses_the_run(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    for _ in range(6):  # every slot taken
        pool.acquire(timeout=0)
    result = pool.acquire(timeout=0.2)
    assert result['ok'] is False
    assert 'browser test' in result['error']
    # The host is still full, and the refused run took no slot.
    assert pool.status()['running'] == 6
    assert pool.status()['waiting'] == 0


def test_releasing_frees_the_slot(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    pool.acquire(timeout=0)
    pool.release()
    assert pool.status()['running'] == 0
    assert pool.acquire(timeout=0)['ok'] is True


def test_the_status_carries_running_waiting_and_cap(monkeypatch):
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    pool.acquire(timeout=0)
    status = pool.status()
    assert status['running'] == 1
    assert status['waiting'] == 0
    assert status['cap'] == 6


# ---------------------------------------------------------------------------
# Which scripts take a slot
# ---------------------------------------------------------------------------

BROWSER_SCRIPT = """
# browser-isolated: this script drives its own Chrome (own debug port, own profile)
_target_rules = {"browser_isolated": True}

import time

def main():
    print("hello")
    time.sleep(1.5)

main()
"""

PLAIN_SCRIPT = """
def main():
    print("hello")

main()
"""

BROKEN_SCRIPT = "def main(:\n    pass\n"


def test_a_browser_isolated_script_is_recognised(tmp_path):
    script = tmp_path / "browser_script.py"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")
    assert executor_mod._script_is_browser_isolated(str(script)) is True


def test_a_plain_script_is_not_browser_isolated(tmp_path):
    script = tmp_path / "plain_script.py"
    script.write_text(PLAIN_SCRIPT, encoding="utf-8")
    assert executor_mod._script_is_browser_isolated(str(script)) is False


def test_a_broken_script_does_not_break_the_run(tmp_path):
    script = tmp_path / "broken_script.py"
    script.write_text(BROKEN_SCRIPT, encoding="utf-8")
    assert executor_mod._script_is_browser_isolated(str(script)) is False


def test_a_missing_script_is_not_browser_isolated():
    assert executor_mod._script_is_browser_isolated('') is False
    assert executor_mod._script_is_browser_isolated('/nope/does-not-exist.py') is False


# ---------------------------------------------------------------------------
# The slot is taken and given back around the run
# ---------------------------------------------------------------------------

def _python_on_path(tmp_path, monkeypatch):
    """The executor runs `python <script>`; some boxes only have `python3`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "python"
    shim.write_text('#!/bin/sh\nexec python3 "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


def test_a_browser_run_takes_a_slot_and_gives_it_back(tmp_path, monkeypatch):
    _python_on_path(tmp_path, monkeypatch)
    """The whole point: the host's browser count grows while a browser run runs."""
    monkeypatch.setenv('VPT_MAX_PARALLEL_BROWSER_RUNS', '6')
    pool = BrowserSlotPool()
    monkeypatch.setattr(executor_mod, 'get_browser_slot_pool', lambda: pool)

    script = tmp_path / "browser_script.py"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")

    executor = executor_mod.ScriptExecutor(script_name="browser_script", device_id="host")
    seen = {}

    def watch_while_running():
        time.sleep(0.4)
        seen['during'] = pool.status()['running']

    watcher = threading.Thread(target=watch_while_running, daemon=True)
    watcher.start()
    result = executor._execute_script_subprocess(str(script), "", "browser_script", time.time())
    watcher.join(timeout=5)

    assert result.get('exit_code') == 0, result.get('stdout')
    assert seen.get('during') == 1, "the run should hold a browser slot while it runs"
    assert pool.status()['running'] == 0, "the slot must come back when the run ends"


def test_a_plain_script_takes_no_browser_slot(tmp_path, monkeypatch):
    _python_on_path(tmp_path, monkeypatch)
    pool = BrowserSlotPool()
    monkeypatch.setattr(executor_mod, 'get_browser_slot_pool', lambda: pool)

    script = tmp_path / "plain_script.py"
    script.write_text(PLAIN_SCRIPT, encoding="utf-8")

    executor = executor_mod.ScriptExecutor(script_name="plain_script", device_id="host")
    executor._execute_script_subprocess(str(script), "", "plain_script", time.time())

    assert pool.status()['running'] == 0


def test_a_browser_run_is_refused_when_the_host_stays_full(tmp_path, monkeypatch):
    """The cap is not walked around: with no slot free, the run does not start."""
    _python_on_path(tmp_path, monkeypatch)
    pool = BrowserSlotPool()
    monkeypatch.setattr(executor_mod, 'get_browser_slot_pool', lambda: pool)
    monkeypatch.setenv('VPT_BROWSER_SLOT_WAIT_SECONDS', '0')

    script = tmp_path / "browser_script.py"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")

    # The host is full: every slot is taken by a browser run that is still going.
    for _ in range(6):
        pool.acquire(timeout=0)

    executor = executor_mod.ScriptExecutor(script_name="browser_script", device_id="host")
    result = executor._execute_script_subprocess(str(script), "", "browser_script", time.time())

    assert result.get('success') is False
    assert 'Browser slot unavailable' in result.get('stderr', '')
    assert pool.status()['running'] == 6


def test_a_waiting_run_says_so_on_the_live_run_page(tmp_path, monkeypatch):
    """A run that waits for a slot must not look like a run that is stuck."""
    _python_on_path(tmp_path, monkeypatch)
    pool = BrowserSlotPool()
    monkeypatch.setattr(executor_mod, 'get_browser_slot_pool', lambda: pool)

    script = tmp_path / "browser_script.py"
    script.write_text(BROWSER_SCRIPT, encoding="utf-8")

    monkeypatch.setenv('VPT_BROWSER_SLOT_WAIT_SECONDS', '0')  # do not sit in the wait
    messages = []
    executor = executor_mod.ScriptExecutor(script_name="browser_script", device_id="host")
    monkeypatch.setattr(executor, 'emit_run_progress', lambda message: messages.append(message))

    for _ in range(6):  # the host is full
        pool.acquire(timeout=0)

    executor._execute_script_subprocess(str(script), "", "browser_script", time.time())

    assert any('Waiting for a free browser slot' in message for message in messages), messages
    assert any('6/6' in message for message in messages), messages
