"""
Stale-while-revalidate cache for the Monitoring > Analytics sections.

WHY NOT A PLAIN TTL
A plain 60s TTL means that every 60 seconds exactly one unlucky request pays the
full query cost while everyone else is served instantly. That is the worst
distribution of a fixed cost: the person who happens to arrive at the wrong moment
gets the slow page. Here a value has two windows instead:

    inside `fresh`            -> serve it
    past fresh, inside stale  -> serve the STALE value NOW, refresh in the background
    past `stale`              -> block and compute (only after nobody looked for an hour)

so no user ever waits for a refresh during normal use.

On top of that, `start_prewarm()` refreshes every registered section on a timer from
boot, which means in practice even the first request after a deploy is a dict lookup.

WHY AN IN-PROCESS DICT IS ENOUGH
vpt-server deliberately runs ONE gevent worker (see docs/agent/infra). One process
means one dict, no cross-worker inconsistency, and greenlets are already the
concurrency primitive — so a background refresh is `spawn()`, not a thread pool or
Redis. If the worker count ever changes, this becomes N independent caches: still
correct, just N times the refresh traffic. That is the only coupling.
"""

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

# gevent is what the server runs under, but the module is imported by tests and by
# `python app.py` runs that may not have monkey-patched yet. Fall back to a plain
# thread so importing this never forces a gevent dependency on a caller.
try:  # pragma: no cover - trivial import guard
    from gevent import spawn as _spawn, sleep as _sleep
    _HAVE_GEVENT = True
except ImportError:  # pragma: no cover
    _HAVE_GEVENT = False

    def _spawn(fn, *args, **kwargs):
        t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
        t.start()
        return t

    def _sleep(seconds):
        time.sleep(seconds)


class _Entry:
    __slots__ = ('value', 'computed_at', 'refreshing', 'error')

    def __init__(self, value: Any, computed_at: float):
        self.value = value
        self.computed_at = computed_at
        self.refreshing = False
        self.error: Optional[str] = None


class SectionCache:
    """One cache for all sections, keyed (section, team_id)."""

    def __init__(self):
        self._entries: Dict[Tuple[str, Optional[str]], _Entry] = {}
        self._lock = threading.RLock()
        # section -> (loader, fresh_seconds, stale_seconds)
        self._loaders: Dict[str, Tuple[Callable[[Optional[str]], Any], float, float]] = {}
        self._prewarm_started = False

    # -- registration ------------------------------------------------------

    def register(self, section: str, loader: Callable[[Optional[str]], Any],
                 fresh: float, stale: float) -> None:
        """Declare a section, how to compute it, and how long its value lives.

        `fresh`/`stale` are per section on purpose: 'is this device up' and 'how many
        incidents on the 3rd of last month' do not deserve the same window.
        """
        if stale < fresh:
            raise ValueError(f"{section}: stale ({stale}s) must be >= fresh ({fresh}s)")
        self._loaders[section] = (loader, fresh, stale)

    def sections(self):
        return sorted(self._loaders)

    # -- reading -----------------------------------------------------------

    def get(self, section: str, team_id: Optional[str] = None) -> Tuple[Any, str]:
        """Return (value, age_state) where age_state is fresh|stale|cold.

        Raises KeyError for an unregistered section so the route can 404 rather than
        letting an unknown path fall through to the auto_proxy blueprint.
        """
        if section not in self._loaders:
            raise KeyError(section)

        loader, fresh, stale = self._loaders[section]
        key = (section, team_id)
        now = time.time()

        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                age = now - entry.computed_at
                if age <= fresh:
                    return entry.value, 'fresh'
                if age <= stale:
                    # Serve stale immediately; refresh behind the caller's back.
                    if not entry.refreshing:
                        entry.refreshing = True
                        _spawn(self._refresh, section, team_id)
                    return entry.value, 'stale'

        # Nothing usable: compute inline. Only reachable when nobody has asked for
        # this section in `stale` seconds, or on the very first call before pre-warm.
        value = self._compute(section, team_id)
        return value, 'cold'

    # -- refreshing --------------------------------------------------------

    def _compute(self, section: str, team_id: Optional[str]) -> Any:
        loader, _fresh, _stale = self._loaders[section]
        value = loader(team_id)
        with self._lock:
            self._entries[(section, team_id)] = _Entry(value, time.time())
        return value

    def _refresh(self, section: str, team_id: Optional[str]) -> None:
        """Background refresh. A failure must never evict a good stale value —
        serving slightly old numbers beats serving an error page."""
        key = (section, team_id)
        try:
            self._compute(section, team_id)
        except Exception as e:  # noqa: BLE001 - deliberately broad, see docstring
            print(f"[@section_cache:_refresh] {section} failed, keeping stale value: {e}")
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    entry.error = str(e)
        finally:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    entry.refreshing = False

    def invalidate(self, section: Optional[str] = None) -> None:
        """Drop cached values. No section = everything. Used by tests."""
        with self._lock:
            if section is None:
                self._entries.clear()
            else:
                for key in [k for k in self._entries if k[0] == section]:
                    del self._entries[key]

    # -- pre-warm ----------------------------------------------------------

    def start_prewarm(self, team_id: Optional[str], interval: float = 30.0) -> None:
        """Keep every section warm for one team from boot.

        Only the default team is pre-warmed: the tenant list is unbounded and
        pre-warming all of it would turn a glance page into a background load
        generator. Other teams fall through to stale-while-revalidate, which is the
        correct trade — they pay once, then they are warm too.
        """
        if self._prewarm_started:
            return
        self._prewarm_started = True

        def loop():
            while True:
                for section in list(self._loaders):
                    try:
                        self._compute(section, team_id)
                    except Exception as e:  # noqa: BLE001
                        print(f"[@section_cache:prewarm] {section} failed: {e}")
                _sleep(interval)

        _spawn(loop)
        print(f"[@section_cache] pre-warm started: {len(self._loaders)} sections "
              f"every {interval}s (gevent={_HAVE_GEVENT})")

    def stats(self) -> Dict[str, Any]:
        """Cache state, for the /server/analytics/_cache debug route."""
        now = time.time()
        with self._lock:
            return {
                'gevent': _HAVE_GEVENT,
                'prewarm': self._prewarm_started,
                'entries': [
                    {
                        'section': section,
                        'team_id': team_id,
                        'age_seconds': round(now - e.computed_at, 1),
                        'refreshing': e.refreshing,
                        'last_error': e.error,
                    }
                    for (section, team_id), e in sorted(
                        self._entries.items(), key=lambda kv: kv[0][0]
                    )
                ],
            }


# One cache for the process.
analytics_cache = SectionCache()
