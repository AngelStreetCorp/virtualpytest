"""
Audit trail writer (TASK-154) — one append-only table, ``public.audit_events``.

Schema: setup/db/schema/079_audit_events.sql. Every user, AI agent, host and cron action lands here.

Design constraints (same shape as ``lock_session_recorder``):
- ``record`` only enqueues (``queue.put_nowait``); all DB I/O happens on one lazy daemon worker, which
  drains up to ``BATCH_SIZE`` rows per cycle into a single insert. Auditing must never be the reason a
  request fails: nothing here raises, a full queue drops the row with a warning.
- Best-effort, bounded loss: at most ``QUEUE_MAX`` rows wait in memory (plus one in-flight batch). A failed
  batch is retried ``INSERT_ATTEMPTS`` times with backoff on the worker thread before it is dropped. Every
  loss is counted (``stats()``: dropped_full, dropped_failed) and logged once a minute while it changes.
  There is no durable outbox: a process restart loses what is still queued.
- ``meta`` is redacted: sensitive-looking keys dropped, strings capped, depth capped.
- The raw caller IP is stored only when ``VPT_AUDIT_STORE_RAW_IP=1``; otherwise only a salted hash.
"""

from __future__ import annotations

import hashlib
import os
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

ACTOR_KINDS = ('user', 'agent', 'host', 'cron', 'service', 'system')
CATEGORIES = ('auth', 'api', 'control', 'ai', 'deploy', 'test', 'admin', 'system')
OUTCOMES = ('ok', 'denied', 'error', 'refused')

BATCH_SIZE = 200
QUEUE_MAX = 10000
STRING_CAP = 300
TABLE = 'audit_events'
# Retention is a DELETE on the worker's own cycle, not a new service. 90 days until the owner sets it
# from the measured volume.
RETENTION_DAYS_DEFAULT = 90
RETENTION_DAYS_MIN = 7
RETENTION_DAYS_MAX = 3650
SWEEP_INTERVAL_SECONDS = 6 * 3600
# A failed batch gets this many tries, sleeping RETRY_BACKOFF_SECONDS[i] before try i+1, then is dropped.
INSERT_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1.0, 4.0)
STATS_LOG_INTERVAL_SECONDS = 60

# Identities the auth middleware manufactures; they are never people.
SYNTHETIC_PRINCIPALS = {
    'auto_signed': 'system',
    'service_api_key': 'service',
    'open_mode': 'system',
    'public_key': 'service',
}

_SENSITIVE_KEY_PARTS = ('password', 'secret', 'token', 'api_key', 'apikey', 'authorization', 'cookie',
                        'credential', 'private', 'env', 'prompt', 'response', 'content', 'output', 'body')

_events: "queue.Queue" = queue.Queue(maxsize=QUEUE_MAX)
_worker_started = False
_worker_guard = threading.Lock()
_stats_lock = threading.Lock()
_stats: Dict[str, int] = {'dropped_full': 0, 'dropped_failed': 0, 'team_rejected': 0}


def _count(name: str, n: int = 1) -> None:
    with _stats_lock:
        _stats[name] = _stats.get(name, 0) + n


def stats() -> Dict[str, int]:
    """Loss counters since process start, plus the rows still queued."""
    with _stats_lock:
        out = dict(_stats)
    out['queued'] = _events.qsize()
    return out


def actor_for(user_id: Optional[str]) -> str:
    """actor_kind for a request principal: synthetic ids are never 'user'."""
    if not user_id:
        return 'system'
    return SYNTHETIC_PRINCIPALS.get(user_id, 'user')


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return '…'
    if isinstance(value, str):
        return value if len(value) <= STRING_CAP else value[:STRING_CAP] + '…'
    if isinstance(value, dict):
        return {str(k)[:60]: _redact(v, depth + 1) for k, v in list(value.items())[:30]
                if not any(part in str(k).lower() for part in _SENSITIVE_KEY_PARTS)}
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _redact(str(value), depth + 1)


def network_info(ip: Optional[str], user_agent: Optional[str]) -> Optional[Dict[str, Any]]:
    """{ip_hash, user_agent}, plus the raw ip only under VPT_AUDIT_STORE_RAW_IP=1."""
    if not ip and not user_agent:
        return None
    out: Dict[str, Any] = {}
    if ip:
        salt = os.environ.get('VPT_AUDIT_IP_SALT', 'vpt-audit')
        out['ip_hash'] = hashlib.sha256(f'{salt}:{ip}'.encode()).hexdigest()[:16]
        if os.environ.get('VPT_AUDIT_STORE_RAW_IP') == '1':
            out['ip'] = ip[:64]
    if user_agent:
        out['user_agent'] = user_agent[:200]
    return out


def valid_team_id(team_id: Any) -> Optional[str]:
    """Canonical UUID string, or None (counted as team_rejected when something was supplied but is not a UUID)."""
    if not team_id:
        return None
    try:
        return str(uuid.UUID(str(team_id).strip()))
    except (ValueError, AttributeError):
        _count('team_rejected')
        return None


def note_team_rejected() -> None:
    _count('team_rejected')


def build_row(*, category: str, action: str, actor_kind: str = 'system', actor_id: Optional[str] = None,
              actor_email: Optional[str] = None, actor_role: Optional[str] = None,
              team_id: Optional[str] = None, target: Optional[str] = None, outcome: str = 'ok',
              method: Optional[str] = None, status_code: Optional[int] = None,
              duration_ms: Optional[int] = None, request_id: Optional[str] = None,
              network: Optional[Dict[str, Any]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if actor_kind not in ACTOR_KINDS:
        actor_kind = 'system'
    if category not in CATEGORIES:
        category = 'system'
    if outcome not in OUTCOMES:
        outcome = 'ok'
    row = {
        'team_id': valid_team_id(team_id),
        'actor_kind': actor_kind,
        'actor_id': str(actor_id)[:128] if actor_id else None,
        'actor_email': str(actor_email)[:200] if actor_email else None,
        'actor_role': actor_role,
        'category': category,
        'action': str(action)[:200],
        'target': str(target)[:300] if target else None,
        'outcome': outcome,
        'method': method,
        'status_code': status_code,
        'duration_ms': duration_ms,
        'request_id': request_id,
        'network': network,
        'meta': _redact(meta or {}),
    }
    return row


def record(**fields: Any) -> bool:
    """Enqueue one audit row. Never raises; returns False when the row was dropped."""
    try:
        row = build_row(**fields)
        _ensure_worker()
        _events.put_nowait(row)
        return True
    except queue.Full:
        _count('dropped_full')
        print(f"⚠️ [AuditEvents] Queue full, dropping {fields.get('action')}")
    except Exception as exc:
        print(f"⚠️ [AuditEvents] Could not enqueue {fields.get('action')}: {exc}")
    return False


def _ensure_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    with _worker_guard:
        if _worker_started:
            return
        threading.Thread(target=_worker_loop, name='audit-events', daemon=True).start()
        _worker_started = True


def drain_batch(limit: int = BATCH_SIZE, timeout: float = 5.0) -> List[Dict[str, Any]]:
    """Block for the first row, then take whatever else is already queued, up to ``limit``."""
    try:
        batch = [_events.get(timeout=timeout)]
    except queue.Empty:
        return []
    while len(batch) < limit:
        try:
            batch.append(_events.get_nowait())
        except queue.Empty:
            break
    return batch


def insert_batch(rows: List[Dict[str, Any]]) -> bool:
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    client = get_supabase_client()
    if client is None or not rows:
        return False
    client.table(TABLE).insert(rows).execute()
    return True


def insert_with_retry(batch: List[Dict[str, Any]], sleep=time.sleep) -> bool:
    """Insert ``batch``, retrying with backoff; on final failure count the rows as dropped_failed."""
    last_error = 'no database client'
    for attempt in range(INSERT_ATTEMPTS):
        try:
            if insert_batch(batch):
                return True
        except Exception as exc:
            last_error = str(exc)
        if attempt < INSERT_ATTEMPTS - 1:
            sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
    _count('dropped_failed', len(batch))
    print(f"⚠️ [AuditEvents] Dropped {len(batch)} rows after {INSERT_ATTEMPTS} attempts: {last_error}")
    return False


def _worker_loop() -> None:
    print("🧾 [AuditEvents] Worker started")
    last_sweep = 0.0
    last_stats_log = 0.0
    last_logged: Dict[str, int] = {}
    while True:
        now = time.time()
        if now - last_stats_log >= STATS_LOG_INTERVAL_SECONDS:
            last_stats_log = now
            snap = stats()
            if (snap['dropped_full'] or snap['dropped_failed'] or snap['team_rejected']) and snap != last_logged:
                print(f"⚠️ [AuditEvents] Loss counters: {snap}")
            last_logged = snap
        if now - last_sweep > SWEEP_INTERVAL_SECONDS:
            last_sweep = now
            try:
                deleted = delete_older_than(retention_days())
                if deleted:
                    print(f"🧾 [AuditEvents] Retention sweep deleted {deleted} rows")
            except Exception as exc:
                print(f"⚠️ [AuditEvents] Retention sweep failed: {exc}")
        batch = drain_batch()
        if not batch:
            continue
        insert_with_retry(batch)


def clamp_retention_days(value: Any) -> int:
    """Safe retention in days: unparsable -> default, otherwise clamped to [MIN, MAX]. Logs what it changed."""
    try:
        days = int(str(value).strip())
    except (TypeError, ValueError):
        print(f"⚠️ [AuditEvents] VPT_AUDIT_RETENTION_DAYS={value!r} is not a number, using {RETENTION_DAYS_DEFAULT}")
        return RETENTION_DAYS_DEFAULT
    clamped = max(RETENTION_DAYS_MIN, min(RETENTION_DAYS_MAX, days))
    if clamped != days:
        print(f"⚠️ [AuditEvents] VPT_AUDIT_RETENTION_DAYS={days} outside {RETENTION_DAYS_MIN}..{RETENTION_DAYS_MAX}, using {clamped}")
    return clamped


def retention_days() -> int:
    raw = os.environ.get('VPT_AUDIT_RETENTION_DAYS')
    return RETENTION_DAYS_DEFAULT if raw is None or raw.strip() == '' else clamp_retention_days(raw)


def delete_older_than(days: int) -> int:
    """Retention sweep: delete rows older than ``days`` (clamped, so no caller can wipe the table). Returns the number deleted."""
    from datetime import datetime, timedelta, timezone
    days = clamp_retention_days(days)
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = get_supabase_client().table(TABLE).delete().lt('at', cutoff).execute()
    return len(res.data or [])


def list_events(team_id: str, cutoff_iso: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Read path for the Activity tab. Filters by team_id."""
    from shared.src.lib.utils.supabase_utils import get_supabase_client
    res = get_supabase_client().table(TABLE) \
        .select('id,at,actor_kind,actor_id,actor_email,actor_role,category,action,target,outcome,status_code,meta') \
        .eq('team_id', team_id).gte('at', cutoff_iso) \
        .order('at', desc=True).limit(limit).execute()
    return res.data or []


def cron(name: str, outcome: str = 'ok', **meta: Any) -> bool:
    """One ``cron.run`` row for a timer script. Synchronous (the script is about to exit); never raises."""
    try:
        return insert_batch([build_row(category='system', action='cron.run', actor_kind='cron',
                                       actor_id=name, target=name, outcome=outcome, meta=meta)])
    except Exception as exc:
        print(f"⚠️ [AuditEvents] cron row for {name} not written: {exc}")
        return False
