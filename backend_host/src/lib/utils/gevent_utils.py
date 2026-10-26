"""Run blocking work without stalling vpt-host's gevent hub.

vpt-host serves Flask-SocketIO on gevent WITHOUT monkey patching, so a blocking socket recv,
``subprocess.run`` or ``time.sleep`` on a request greenlet stops every other request (stream
playlists included) until it returns.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


def off_hub(fn: Callable[..., Any], *args: Any) -> Any:
    """Run ``fn(*args)`` without stalling the gevent hub (BUG-0511, BUG-0512).

    On the vpt-host request path (a greenlet on the main thread, hub running) the call goes to an
    OS thread of the hub's threadpool and the greenlet waits cooperatively, so other requests keep
    being served. Anywhere else (a script process, a background thread, a pool worker) it runs
    inline.
    """
    try:
        import gevent
        from gevent._hub_local import get_hub_if_exists
    except ImportError:
        return fn(*args)
    hub = get_hub_if_exists()
    if (hub is None or gevent.getcurrent() is hub
            or threading.current_thread() is not threading.main_thread()):
        return fn(*args)
    return hub.threadpool.apply(fn, args)
