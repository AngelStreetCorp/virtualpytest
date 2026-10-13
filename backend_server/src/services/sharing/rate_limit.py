"""In-process sliding-window limiter for the token-only share read.

Per-process by design (like the public docs Q&A limiter): with N gunicorn
workers the effective ceiling is N times the configured limits. It bounds
token guessing and scraping; it is not a quota system.

Keys are the connection's peer address (``request.remote_addr``), never a
forwarded header: X-Forwarded-For is client-controlled and this server has no
trusted-proxy configuration to tell a proxy-added entry from a forged one.
Behind a reverse proxy every reader therefore shares the proxy's bucket, which
makes the ceilings global — the safe direction for a guessing limiter.

Memory is bounded: at most ``MAX_KEYS`` buckets; past that, expired buckets
are dropped first, then the least recently used ones.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Optional, Tuple

LIMITS: Tuple[Tuple[str, int, int], ...] = (
    ('ip', 120, 60),             # any snapshot, per client address: 120 / minute
    ('ip_snapshot', 30, 60),     # one snapshot, per client address: 30 / minute
)
MAX_KEYS = 20000
_LONGEST_WINDOW = max(window for _, _, window in LIMITS)

_lock = threading.Lock()
_buckets: 'OrderedDict[str, Deque[float]]' = OrderedDict()


def _evict(current: float) -> None:
    if len(_buckets) <= MAX_KEYS:
        return
    for key in [k for k, v in _buckets.items() if not v or current - v[-1] > _LONGEST_WINDOW]:
        del _buckets[key]
    while len(_buckets) > MAX_KEYS:
        _buckets.popitem(last=False)


def allow(client_address: str, snapshot_id: str, now: Optional[float] = None) -> bool:
    """Record one read and say whether it is within the limits.

    ``snapshot_id`` must already be validated (a UUID) so arbitrary path
    segments cannot create buckets.
    """
    current = time.monotonic() if now is None else now
    keys = {'ip': f'ip:{client_address}', 'ip_snapshot': f'ips:{client_address}:{snapshot_id}'}
    with _lock:
        for kind, max_requests, window in LIMITS:
            bucket = _buckets.get(keys[kind])
            if bucket is None:
                continue
            while bucket and current - bucket[0] > window:
                bucket.popleft()
            if len(bucket) >= max_requests:
                _buckets.move_to_end(keys[kind])
                return False
        for kind, _, _ in LIMITS:
            bucket = _buckets.setdefault(keys[kind], deque())
            bucket.append(current)
            _buckets.move_to_end(keys[kind])
        _evict(current)
    return True


def size() -> int:
    with _lock:
        return len(_buckets)


def reset() -> None:
    with _lock:
        _buckets.clear()
