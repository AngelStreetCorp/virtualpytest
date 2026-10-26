#!/usr/bin/env python3
"""How many browser runs one host runs at the same time.

A browser-isolated web script drives its OWN Chrome - its own debug port, its own profile
directory - so several of them can share one host instead of queueing behind each other
(TASK-146). The device lock stays with the first of them; the others run beside it.

That makes the **host** the scarce resource rather than the device: every run is a Chromium
with its own profile, and the host's RAM and CPU are finite. This module is the cap that
keeps that from turning into a pile-up.

The cap follows the host's memory: a browser test costs about 600 MB, the host keeps
about 1.2 GB for itself, and the rest is what the browsers may use - never more than 6
and never less than 1. A 4 GB host (the lab's smallest) therefore carries 4 browser
tests, a 16 GB host 6. ``VPT_MAX_PARALLEL_BROWSER_RUNS`` overrides it per host.

The host owns the count, because the host is where the Chromes actually run: every path
that starts a script on a host - the API, the Run page, a queued deployment the host
scheduler picks up - goes through the same executor, so the cap cannot be walked around.

A run that finds the host full **waits** for a free slot (bounded by
``VPT_BROWSER_SLOT_WAIT_SECONDS``) instead of piling on or failing.

The cap counts what the host is **carrying**, not only what this process believes it started.
A run gives its slot back when it ends whether or not its browser died, so a Chromium that
outlives its run used to be invisible here: the host read as ``running: 0`` while carrying
nine of them (~2 GB of a 3.9 GB host, one per hour — BUG-0760). The count is therefore taken
against the ports themselves, and a browser nobody owns is budget the host cannot use.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

DEFAULT_MAX_PARALLEL_BROWSER_RUNS = 6
DEFAULT_SLOT_WAIT_SECONDS = 600

# What one browser test costs the host. A Chrome with a video playing takes roughly
# 300-800 MB; 600 MB is the middle, and the host keeps the rest for its own work
# (capture, monitoring, the KPI units) plus the browser run's own page loads.
MEMORY_PER_BROWSER_RUN_MB = 600
MEMORY_RESERVED_FOR_THE_HOST_MB = 1200
MIN_PARALLEL_BROWSER_RUNS = 1


def _total_memory_mb() -> Optional[int]:
    """The host's total memory in MB, or None when it cannot be read."""
    try:
        with open('/proc/meminfo', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    try:
        import psutil  # noqa: PLC0415 - optional, only used when /proc is not there
        return int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:
        return None


def memory_derived_cap() -> int:
    """How many browser runs this host can carry, from its memory.

    A browser test costs about MEMORY_PER_BROWSER_RUN_MB and the host keeps
    MEMORY_RESERVED_FOR_THE_HOST_MB for itself; the rest is what the browsers may use.
    Never more than DEFAULT_MAX_PARALLEL_BROWSER_RUNS, never less than one.

    A 4 GB host (the lab's smallest) gets 4, a 16 GB host gets the maximum of 6. Six
    Chromes on a 4 GB box would thrash it - which is the very pile-up the cap exists to
    prevent.
    """
    total_mb = _total_memory_mb()
    if not total_mb:
        return DEFAULT_MAX_PARALLEL_BROWSER_RUNS
    spare_mb = total_mb - MEMORY_RESERVED_FOR_THE_HOST_MB
    if spare_mb <= 0:
        return MIN_PARALLEL_BROWSER_RUNS
    cap = spare_mb // MEMORY_PER_BROWSER_RUN_MB
    return max(MIN_PARALLEL_BROWSER_RUNS, min(DEFAULT_MAX_PARALLEL_BROWSER_RUNS, int(cap)))


def max_parallel_browser_runs() -> int:
    """How many browser runs one host may run at the same time.

    VPT_MAX_PARALLEL_BROWSER_RUNS wins when it is set (an operator's decision for that
    host); otherwise the cap follows the host's memory. Read from the environment on
    every call, so a change needs no restart; anything unparseable or below 1 falls back
    to the memory-derived cap.
    """
    raw = os.environ.get('VPT_MAX_PARALLEL_BROWSER_RUNS', '')
    if str(raw).strip():
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return memory_derived_cap()
        return value if value >= 1 else memory_derived_cap()
    return memory_derived_cap()


def slot_wait_seconds() -> int:
    """How long a run waits for a free browser slot before giving up."""
    raw = os.environ.get('VPT_BROWSER_SLOT_WAIT_SECONDS', '')
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_SLOT_WAIT_SECONDS
    return value if value >= 0 else DEFAULT_SLOT_WAIT_SECONDS


class BrowserSlotPool:
    """The browser slots of ONE host."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._running = 0
        self._waiting = 0

    def acquire(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Take a browser slot, waiting for one if the host is full.

        What the host is CARRYING counts, not only what this pool started: a browser that
        outlived its run is budget nobody can use, so `leaked_browser_count()` is added to
        the runs in flight (BUG-0760). A host carrying four dead browsers and a cap of four
        admits nothing more, and says why.

        Returns ``{'ok': True, 'running': n, 'cap': cap, 'waited': seconds}`` when a slot
        was taken, and ``{'ok': False, ...}`` when the wait ran out.
        """
        cap = max_parallel_browser_runs()
        deadline = time.time() + (timeout if timeout is not None else slot_wait_seconds())
        # One reclaim attempt per acquire, and only once the host is actually full: a healthy
        # host is admitted on the first sweep below and never reaches this.
        reap_attempted = False
        with self._condition:
            self._waiting += 1
            try:
                while True:
                    # Cached for a few seconds, so this sweep cannot make the wait loop
                    # expensive even though it runs under the condition.
                    leaked = leaked_browser_count()
                    if self._running + leaked < cap:
                        self._running += 1
                        return {
                            'ok': True,
                            'running': self._running,
                            'leaked': leaked,
                            'cap': cap,
                            'waited': 0,
                        }
                    # The host is full and part of that load belongs to runs that already
                    # ended. Reclaim it here, where a run is waiting for the slot, rather than
                    # leaving an unattended host wedged for ever (BUG-0760 part 1).
                    if leaked and not reap_attempted:
                        reap_attempted = True
                        try:
                            from shared.src.lib.utils.leaked_browser_reaper import reap_leaked_browsers
                            reaped = reap_leaked_browsers(grace_seconds=3.0)
                            if reaped.get('reaped'):
                                print(f"[browser_run_slots] reclaimed {len(reaped['reaped'])} browser(s) "
                                      f"left by finished runs; the cap is honest again")
                                continue
                        except Exception as e:  # noqa: BLE001 - never fail a run over a reap
                            print(f"[browser_run_slots] reclaim pass failed ({type(e).__name__}: {e}); "
                                  f"waiting for a slot as before")
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        if leaked:
                            error = (f'host carries {leaked} browser(s) left over from finished '
                                     f'runs, plus {self._running} running (limit {cap})')
                        else:
                            error = f'host already runs {self._running} browser test(s) (limit {cap})'
                        return {
                            'ok': False,
                            'running': self._running,
                            'leaked': leaked,
                            'cap': cap,
                            'waited': slot_wait_seconds() - max(remaining, 0),
                            'error': error,
                        }
                    self._condition.wait(min(remaining, 5.0))
            finally:
                self._waiting -= 1

    def release(self) -> None:
        """Give a browser slot back and wake a run that is waiting for one."""
        with self._condition:
            if self._running > 0:
                self._running -= 1
            self._condition.notify_all()

    def status(self) -> Dict[str, Any]:
        """How many browsers run here, how many wait, how many leaked, and the cap."""
        with self._condition:
            return {
                'running': self._running,
                'waiting': self._waiting,
                'leaked': leaked_browser_count(),
                'cap': max_parallel_browser_runs(),
            }


_pool = BrowserSlotPool()


# ── what the host is CARRYING, not what it believes it started (BUG-0760) ─────────

# How far above the run range to look for a browser nobody owns. Runs take 9300+; a
# leak of a few ports is what we are after, not an unbounded scan of the machine.
LEAK_SCAN_SPAN = 64

# The sweep opens a connection per port, so it is cached for a few seconds. The wait
# loop calls it every 5 s slice and the dashboard calls it per status read; neither
# wants 64 connect attempts each time.
_LEAK_CACHE_SECONDS = 10.0
_leak_cache: Dict[str, Any] = {'at': 0.0, 'ports': ()}


def leaked_browser_ports() -> tuple:
    """Run ports holding a browser that belongs to no live run.

    A run gives its slot back when it ends whether or not its browser died, so a Chromium
    that outlives its run is invisible to the slot pool: the host reports ``running: 0``
    while it carries the body (BUG-0760). These are the ports where that happened.

    **Read-only. This never kills anything.** Reaping a leaked browser is deliberate work
    done by someone who has looked at the list, and signalling a browser's process group
    without checking what else shares that group took a lab host's SSH down with it on
    2026-10-22 (see BUG-0760).

    A port with a listener AND no live owner is a leak. A port with a live owner is a run
    in progress, and is already counted by the pool — counting it twice would make the cap
    stricter than the host is.
    """
    from shared.src.lib.utils import browser_port_allocator as allocator

    now = time.time()
    if now - _leak_cache['at'] < _LEAK_CACHE_SECONDS:
        return _leak_cache['ports']

    leaked = []
    try:
        for offset in range(LEAK_SCAN_SPAN):
            port = allocator.RUN_DEBUG_PORT_BASE + offset
            if allocator.is_port_listening(port) and allocator.port_owner_pid(port) is None:
                leaked.append(port)
    except Exception as e:
        # Never let a measurement problem stop a run from starting. A host that cannot
        # be measured is a host we fall back to counting the old way on.
        print(f"[browser_run_slots] leak scan failed ({type(e).__name__}: {e}) — counting runs only")
        leaked = []

    _leak_cache.update({'at': now, 'ports': tuple(leaked)})
    return _leak_cache['ports']


def leaked_browser_count() -> int:
    """How many browsers on this host belong to no live run."""
    return len(leaked_browser_ports())


def invalidate_leak_cache() -> None:
    """Forget the cached sweep so the next read re-measures.

    Called right after a reclaim pass: without this the pool would keep counting browsers
    that no longer exist for up to ``_LEAK_CACHE_SECONDS`` and refuse a run it could admit.
    """
    _leak_cache['at'] = 0.0


def get_browser_slot_pool() -> BrowserSlotPool:
    return _pool


def browser_run_status() -> Dict[str, Any]:
    """The host's browser load - what the dashboard shows as "N browsers running"."""
    return _pool.status()
