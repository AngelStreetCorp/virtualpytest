"""
Async Utilities for Flask Integration

Provides helpers to run async code in synchronous Flask route handlers.
"""

import asyncio
from typing import Any, Coroutine

# Seconds a route handler will wait for its coroutine before giving up.
_RUN_ASYNC_TIMEOUT = 30


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
    # thread — but app.py calls gevent's monkey.patch_all(), so that thread was
    # a greenlet inside the worker's single OS thread. asyncio records "a loop
    # is running" per OS thread, so the forever-loop flagged the whole worker
    # and every later asyncio.run() in it failed with "asyncio.run() cannot be
    # called from a running event loop" — one 404 on POST
    # /server/runtime/instances/<id>/stop silently killed Atlas chat until the
    # next restart. Running the loop here instead keeps it inside the calling
    # greenlet: patch_all() drops select.epoll, so asyncio falls back to the
    # patched select.select and the loop yields to the hub like any other
    # gevent-blocking call, then exits and clears the flag.
    #
    # Consequence: tasks a coroutine spawns with asyncio.create_task do not
    # outlive the request that created them (asyncio.run cancels what is still
    # pending). That only affects /server/runtime/instances/start, whose agent
    # instances would need their own supervisor to survive a request anyway.
    return asyncio.run(asyncio.wait_for(coro, timeout=_RUN_ASYNC_TIMEOUT))
