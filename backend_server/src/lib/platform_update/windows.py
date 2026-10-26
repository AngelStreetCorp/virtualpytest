"""
Standalone maintenance windows (TASK-97), created from Settings -> Maintenance.

A window is not tied to a Platform update run. It has a ``scope``: ``platform`` (banner on every page) or
``devices`` (banner on Devices and Dashboard, a marker next to each covered device name). Same file-based
store pattern as ``runs.py``: ``<state_dir>/maintenance-windows/<window_id>.json`` (state dir = integration_state,
OUTSIDE the project tree so a deploy cannot wipe it - CONTRACTS #23). No database table.

A window is *active* from ``window_start`` until ``window_end`` or until it is ended by hand (``ended_at``).
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend_server.src.lib.platform_update.runs import (
    SCOPES, PlatformUpdateError, RunNotFound, _iso, _now, _parse,
)

KEEP_ENDED_DAYS = 7  # ended / expired windows stay listed for the admin this long
MAX_REASON = 500


class WindowStore:
    """File-backed store; one instance per directory (tests pass a tmp dir)."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self._lock = threading.RLock()

    def _json(self, window_id: str) -> Path:
        if not window_id or not all(c.isalnum() or c in '-_' for c in window_id):
            raise RunNotFound('maintenance window not found')
        return self.dir / f'{window_id}.json'

    def _save(self, win: Dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._json(win['id'])
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(win, ensure_ascii=True), encoding='utf-8')
        os.replace(tmp, path)

    def get(self, window_id: str) -> Dict[str, Any]:
        path = self._json(window_id)
        if not path.is_file():
            raise RunNotFound('maintenance window not found')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _clean(scope: str, device_ids: Optional[List[str]]) -> List[str]:
        if scope not in SCOPES:
            raise PlatformUpdateError(f'scope must be one of {", ".join(SCOPES)}')
        if scope == 'platform':
            return []
        ids = [str(d) for d in (device_ids or []) if str(d).strip()]
        if not ids:
            raise PlatformUpdateError('select at least one device for a device window')
        return list(dict.fromkeys(ids))

    @staticmethod
    def _bounds(window_start: Optional[str], window_end: Optional[str]):
        start_dt = _parse(window_start) if window_start else _now()
        end_dt = _parse(window_end) if window_end else start_dt + timedelta(hours=1)
        if end_dt <= start_dt:
            raise PlatformUpdateError('the end of the window must be after its start')
        return start_dt, end_dt

    # -- transitions --------------------------------------------------------------------------
    def create(self, created_by: str, window_start: Optional[str] = None, window_end: Optional[str] = None,
               reason: str = '', scope: str = 'devices', device_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        ids = self._clean(scope, device_ids)
        start_dt, end_dt = self._bounds(window_start, window_end)
        win = {
            'id': 'mw-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6],
            'created_by': created_by or 'unknown',
            'created_at': _iso(_now()),
            'window_start': _iso(start_dt),
            'window_end': _iso(end_dt),
            'scope': scope,
            'device_ids': ids,
            'reason': (reason or '')[:MAX_REASON],
            'ended_at': None,
        }
        with self._lock:
            self._save(win)
        return win

    def update(self, window_id: str, window_start: Optional[str] = None, window_end: Optional[str] = None,
               reason: Optional[str] = None, scope: Optional[str] = None,
               device_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            win = self.get(window_id)
            if not self._is_current(win):
                raise PlatformUpdateError('this window has ended and can no longer be edited')
            new_scope = scope or win['scope']
            ids = self._clean(new_scope, device_ids if device_ids is not None else win['device_ids'])
            start_dt, end_dt = self._bounds(window_start or win['window_start'], window_end or win['window_end'])
            win.update({'scope': new_scope, 'device_ids': ids, 'window_start': _iso(start_dt),
                        'window_end': _iso(end_dt)})
            if reason is not None:
                win['reason'] = reason[:MAX_REASON]
            self._save(win)
            return win

    def end(self, window_id: str) -> Dict[str, Any]:
        with self._lock:
            win = self.get(window_id)
            if win.get('ended_at'):
                return win
            win['ended_at'] = _iso(_now())
            self._save(win)
            return win

    # -- views --------------------------------------------------------------------------------
    @staticmethod
    def _is_current(win: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        """Not ended by hand and not past its end (it may still be in the future)."""
        now = now or _now()
        return not win.get('ended_at') and _parse(win['window_end']) > now

    @classmethod
    def is_active(cls, win: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        now = now or _now()
        return cls._is_current(win, now) and _parse(win['window_start']) <= now

    def list_all(self) -> List[Dict[str, Any]]:
        """Admin view: upcoming + active + recently ended, newest start first, each with a ``state``."""
        if not self.dir.is_dir():
            return []
        now = _now()
        out = []
        for p in self.dir.glob('*.json'):
            try:
                win = json.loads(p.read_text(encoding='utf-8'))
                gone = _parse(win.get('ended_at') or win['window_end'])
            except (OSError, ValueError, KeyError, PlatformUpdateError):
                continue
            if not self._is_current(win, now) and now - gone > timedelta(days=KEEP_ENDED_DAYS):
                continue
            state = ('ended' if win.get('ended_at') or _parse(win['window_end']) <= now
                     else 'active' if self.is_active(win, now) else 'upcoming')
            out.append({**win, 'state': state})
        out.sort(key=lambda w: w['window_start'], reverse=True)
        return out

    def active(self) -> List[Dict[str, Any]]:
        """Windows in force right now, in the shape of ``RunStore.maintenance()['window']`` (what every user sees)."""
        return [self.public(w) for w in self.list_all() if w['state'] == 'active']

    @staticmethod
    def public(win: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'id': win['id'], 'source': 'settings', 'scope': win['scope'], 'device_ids': win['device_ids'],
            'window_start': win['window_start'], 'window_end': win['window_end'],
            'started_by': win['created_by'], 'reason': win.get('reason', ''),
        }


def default_window_store() -> WindowStore:
    from backend_server.src.lib.utils.integration_state import state_path
    return WindowStore(state_path('maintenance-windows'))
