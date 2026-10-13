"""
Async Utilities for Flask Integration

Provides helpers to run async code in synchronous Flask route handlers, one event loop at a
time per worker.
"""

import asyncio
import sys
import threading
import types
from typing import Any, Callable, Coroutine, Optional

# Seconds a route handler will wait for its coroutine before giving up.
_RUN_ASYNC_TIMEOUT = 30

# One asyncio loop at a time per worker. app.py calls gevent's monkey.patch_all(), so every
# request and background job is a greenlet in ONE OS thread, and asyncio records "a loop is
# running" per OS thread: while one greenlet's loop yields to the hub, any other
# asyncio.run() in the worker fails with "asyncio.run() cannot be called from a running
# event loop". Atlas chats were already queued among themselves, but a Test Prompt
# exploration, the agent background queue, Slack processing and these route helpers ran
# their loops beside them — on the Pi server a chat started during a Test Prompt run
# crashed (2026-10-04, BUG-0126 family). Every loop in the worker goes through this gate;
# threading is monkeypatched, so waiting here yields to other greenlets.
#
# This file is imported both as `agent.async_utils` and `backend_server.src.agent.async_utils`
# (two module objects), so the gate lives in one process-wide slot, not a module global.
_GATE = sys.modules.setdefault(
    "_vpt_worker_loop_gate", types.SimpleNamespace(lock=threading.Lock(), owner=None)  # type: ignore[arg-type]
)


def run_in_worker_loop(coro: Coroutine, on_wait: Optional[Callable[[], None]] = None) -> Any:
    """Run `coro` to completion once the worker's event loop is free.

    `on_wait` is called (once) when another loop holds the gate, e.g. to tell a chat it is
    queued. A nested call from inside a running loop raises instead of deadlocking.
    """
    if _GATE.owner == threading.get_ident():
        coro.close()
        raise RuntimeError("run_in_worker_loop called from inside the worker's running event loop")
    if not _GATE.lock.acquire(blocking=False):
        if on_wait is not None:
            on_wait()
        _GATE.lock.acquire()
    _GATE.owner = threading.get_ident()
    try:
        return asyncio.run(coro)
    finally:
        _GATE.owner = None
        _GATE.lock.release()


def run_async(coro: Coroutine) -> Any:
    """
    Run async coroutine in Flask route handler

    Args:
        coro: Async coroutine to execute

    Returns:
        Result of the coroutine
    """
    # One loop per call, torn down before we return. This used to submit to a
    # process-wide loop kept alive by loop.run_forever() in a background
    # thread — but that thread was a greenlet inside the worker's single OS thread,
    # so the forever-loop flagged the whole worker and every later asyncio.run() in it
    # failed, which could silently kill Atlas chat until the next restart. Running the
    # loop here keeps it inside the calling greenlet: patch_all() drops select.epoll, so
    # asyncio falls back to the patched select.select and the loop yields to the hub like
    # any other gevent-blocking call, then exits and clears the flag.
    #
    # Consequence: tasks a coroutine spawns with asyncio.create_task do not
    # outlive the request that created them (asyncio.run cancels what is still
    # pending). Routes that need a long-lived task must keep their own supervisor.
    return run_in_worker_loop(asyncio.wait_for(coro, timeout=_RUN_ASYNC_TIMEOUT))
