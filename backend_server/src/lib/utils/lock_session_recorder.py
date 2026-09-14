"""
Device lock session recorder.

Persists DeviceLockManager transitions to the device_control_sessions table so
Grafana can compute device occupancy (manual control + script/deployment
executions) from the DB.

Design constraints:
- record_* is called while the lock manager's mutex is held, so it only
  enqueues (uuid + queue.put_nowait). All DB I/O happens on a daemon worker
  thread — a stalled DB can never block or fail lock operations.
- Best-effort: a full queue or DB error drops the event with a log line;
  locking semantics are unaffected.

Lifecycle mapping (one DB row per lock session):
- start: lock created, or ownership transferred (takeover/supersede) — the old
  session is ended and a new row starts.
- touch: heartbeat / re-entrant refresh, throttled to TOUCH_INTERVAL_SECONDS.
- end:   released / superseded / takeover / expired / force_unlock / host_restart.

Server-restart recovery (in-memory locks die with the process, so no end event
is recorded): start_session closes any dangling open row for the device, and
the worker periodically stale-sweeps open rows whose last_seen_at is older than
the script-lock max-age ceiling (see sweep_stale_sessions for why that
threshold is safe with multiple backend_servers sharing the table).
"""

import os
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

TOUCH_INTERVAL_SECONDS = 60
SWEEP_INTERVAL_SECONDS = 600
# Must stay above server_control_routes.SCRIPT_LOCK_TIMEOUT_SECONDS (zombie
# reaper ceiling) so a live non-heartbeating script lock is never swept.
STALE_SWEEP_AFTER_SECONDS = int(os.environ.get('SCRIPT_LOCK_MAX_AGE_SECONDS', 7200)) + 600

_events: "queue.Queue" = queue.Queue(maxsize=10000)
_worker_started = False
_worker_guard = threading.Lock()


def _iso(ts: Optional[float] = None) -> str:
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _enqueue(event: tuple) -> None:
    _ensure_worker()
    try:
        _events.put_nowait(event)
    except queue.Full:
        print(f"⚠️ [LockSessionRecorder] Event queue full, dropping {event[0]} event")


def record_start(lock_data: Dict[str, Any]) -> None:
    """Start a DB session for a freshly created/transferred lock.

    Mutates lock_data: stamps db_session_id so later end/touch events can
    reference the row.
    """
    session_id = str(uuid.uuid4())
    lock_data['db_session_id'] = session_id
    lock_data['db_last_touch'] = float(lock_data.get('locked_at') or time.time())
    _enqueue(('start', {
        'id': session_id,
        'host_name': lock_data.get('host_name'),
        'device_id': lock_data.get('device_id'),
        'owner_type': lock_data.get('owner_type'),
        'owner_session_id': lock_data.get('owner_session_id'),
        'owner_user_id': lock_data.get('owner_user_id'),
        'owner_job_id': lock_data.get('owner_job_id'),
        'lock_reason': lock_data.get('lock_reason'),
        'locked_ip': lock_data.get('locked_ip'),
        'started_at': _iso(lock_data.get('locked_at')),
        'last_seen_at': _iso(lock_data.get('locked_at')),
    }))


def record_end(lock_data: Dict[str, Any], end_reason: str) -> None:
    session_id = lock_data.get('db_session_id')
    if not session_id:
        return
    _enqueue(('end', {'id': session_id, 'end_reason': end_reason, 'ended_at': _iso()}))


def record_touch(lock_data: Dict[str, Any]) -> None:
    """Refresh last_seen_at, throttled so 30s heartbeats don't spam the DB."""
    session_id = lock_data.get('db_session_id')
    if not session_id:
        return
    now = time.time()
    if now - float(lock_data.get('db_last_touch') or 0) < TOUCH_INTERVAL_SECONDS:
        return
    lock_data['db_last_touch'] = now
    _enqueue(('touch', {'id': session_id, 'last_seen_at': _iso(now)}))


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_guard:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name='lock-session-recorder', daemon=True)
        thread.start()
        _worker_started = True


def _worker_loop() -> None:
    from shared.src.lib.database import device_control_sessions_db as sessions_db

    print("📼 [LockSessionRecorder] Worker started")
    last_sweep = 0.0
    while True:
        try:
            kind, payload = _events.get(timeout=SWEEP_INTERVAL_SECONDS)
        except queue.Empty:
            kind, payload = None, None

        try:
            if kind == 'start':
                sessions_db.start_session(payload)
            elif kind == 'end':
                sessions_db.end_session(payload['id'], payload['end_reason'], payload['ended_at'])
            elif kind == 'touch':
                sessions_db.touch_session(payload['id'], payload['last_seen_at'])
        except Exception as exc:
            print(f"⚠️ [LockSessionRecorder] Failed to persist {kind} event: {exc}")

        now = time.time()
        if now - last_sweep > SWEEP_INTERVAL_SECONDS:
            last_sweep = now
            try:
                sessions_db.sweep_stale_sessions(STALE_SWEEP_AFTER_SECONDS)
            except Exception as exc:
                print(f"⚠️ [LockSessionRecorder] Stale sweep failed: {exc}")
