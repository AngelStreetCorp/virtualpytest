"""In-memory rate limiter + metrics for the match_runs dashboard (BUG-0571).

The dashboard polls 6 endpoints every 10s.  With one operator and a 7d
window each poll scans tens of thousands of rows.  Per-team counters stop
one busy team from starving the others and the metrics endpoint exposes
the live shape so the operator can see "is the dashboard hot" without
shipping prometheus_client.

Design notes:
- Counts per (team_id, minute_epoch).  A new minute always has budget; the
  dict is GC'd lazily on every check so it cannot grow unbounded.
- The same dict drives the per-endpoint counter, so the metrics endpoint
  is one read.
- Thread-safe via a single Lock.  The dashboard's load is small (one
  operator per team) and the lock is held for a microsecond at most, so
  a sharded counter would be overkill.
- Default budget is 60 req/min/team (1 req/s sustained), which is 6x the
  dashboard's 10s poll.  Per-endpoint overrides via ``RATE_BUDGETS`` cover
  the heavy ones (``per-device`` and ``distribution`` with a 7d window
  scan far more rows than ``summary``).
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Any, Dict, Tuple


# Per-endpoint budget (requests per minute per team).  Override via env
# (e.g. ``MATCH_RUNS_RATE_BUDGET_PER_DEVICE=20``) to dial it down in
# production when a team grows; the defaults are tuned for one operator
# polling every 10s.  ``0`` disables the limit for that endpoint.
DEFAULT_BUDGETS: Dict[str, int] = {
    'summary': 60,
    'per_device': 30,
    'distribution': 30,
    'sequence': 60,
    'recent': 120,
    'transitions': 60,
    'uncertain': 60,
}


def _budget(endpoint: str) -> int:
    """Resolve a per-endpoint budget.  ``0`` means unlimited."""
    env_key = f'MATCH_RUNS_RATE_BUDGET_{endpoint.upper()}'
    raw = os.environ.get(env_key)
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    return DEFAULT_BUDGETS.get(endpoint, 60)


class MatchRunsRateLimiter:
    """Per-team rate limiter + per-endpoint counter, in-process.

    Single instance per process.  ``record`` both gates the request and
    tallies it, so a denied call still counts toward the 429 metric.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key = (team_id, endpoint, minute_epoch) → count
        self._counts: Dict[Tuple[str, str, int], int] = defaultdict(int)
        # key = (team_id, endpoint) → "denied" count (separately tracked)
        self._denied: Dict[Tuple[str, str], int] = defaultdict(int)
        # most recent decision per (team_id, endpoint) — used for status output
        self._last_decision: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def check(self, team_id: str, endpoint: str) -> Tuple[bool, Dict[str, Any]]:
        """Atomically check + record a request.  Returns ``(allowed, info)``.

        ``info`` has ``budget``, ``used``, ``remaining``, ``window_started_at``
        so the metrics endpoint and the 429 response can show the operator
        the same numbers without re-reading the dict.
        """
        now = time.time()
        minute = int(now // 60)
        budget = _budget(endpoint)
        key = (team_id, endpoint, minute)
        with self._lock:
            self._counts[key] += 1
            used = self._counts[key]
            allowed = budget == 0 or used <= budget
            if not allowed:
                self._denied[(team_id, endpoint)] += 1
            info = {
                'budget': budget,
                'used': used,
                'remaining': max(0, budget - used) if budget else 'unlimited',
                'window_started_at': minute * 60,
                'denied': self._denied.get((team_id, endpoint), 0),
            }
            self._last_decision[(team_id, endpoint)] = info
            return allowed, info

    def snapshot(self, team_id: str | None = None) -> Dict[str, Any]:
        """Return the per-endpoint counters for the metrics endpoint.

        Filters by ``team_id`` when given (the operator's own view) and
        aggregates across all teams when ``None`` (the fleet view).
        """
        now = time.time()
        current_minute = int(now // 60)
        with self._lock:
            # Drop stale buckets so the dict does not grow.
            stale = [k for k in self._counts if k[2] < current_minute - 5]
            for k in stale:
                self._counts.pop(k, None)

            by_endpoint: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {'this_minute': 0, 'denied_total': 0}
            )
            for (tid, ep, minute), n in self._counts.items():
                if team_id is not None and tid != team_id:
                    continue
                if minute == current_minute:
                    by_endpoint[ep]['this_minute'] += n
            for (tid, ep), n in self._denied.items():
                if team_id is not None and tid != team_id:
                    continue
                by_endpoint[ep]['denied_total'] += n
            return {
                'window_started_at': current_minute * 60,
                'team_id': team_id or '*',
                'by_endpoint': dict(by_endpoint),
            }


# Single process-wide instance.  Imported wherever the rate limit is
# enforced so the counters stay consistent.
_instance: MatchRunsRateLimiter | None = None
_instance_lock = threading.Lock()


def get_limiter() -> MatchRunsRateLimiter:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MatchRunsRateLimiter()
    return _instance
