"""
Device Control Sessions Database Operations

Durable history of device lock sessions (manual control + script/deployment
executions) for occupancy analytics. Written best-effort by the backend_server
lock manager via lock_session_recorder — the in-memory DeviceLockManager stays
authoritative for live locking; failures here must never affect lock behavior.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'device_control_sessions'


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_session(session_row: Dict[str, Any]) -> bool:
    """Insert a new open session; closes any dangling open row for the device first.

    A dangling open row can only be a leftover from a server restart (the
    in-memory lock died with the process, so no end event was ever recorded).
    It is closed at its own last_seen_at, not NOW(), to avoid inflating occupancy.
    """
    supabase = get_supabase_client()
    if not supabase:
        return False

    close_dangling_for_device(session_row['host_name'], session_row['device_id'])

    result = supabase.table(TABLE).insert(session_row).execute()
    return bool(result.data)


def end_session(session_id: str, end_reason: str, ended_at: Optional[str] = None) -> bool:
    """Close an open session. No-op if the start insert never landed."""
    supabase = get_supabase_client()
    if not supabase:
        return False

    result = supabase.table(TABLE).update({
        'ended_at': ended_at or _now_iso(),
        'end_reason': end_reason,
    }).eq('id', session_id).is_('ended_at', 'null').execute()
    return bool(result.data)


def touch_session(session_id: str, last_seen_at: Optional[str] = None) -> bool:
    """Refresh last_seen_at on heartbeat (throttled by the recorder)."""
    supabase = get_supabase_client()
    if not supabase:
        return False

    result = supabase.table(TABLE).update({
        'last_seen_at': last_seen_at or _now_iso(),
    }).eq('id', session_id).is_('ended_at', 'null').execute()
    return bool(result.data)


def close_dangling_for_device(host_name: str, device_id: str) -> int:
    """Close open sessions for one device (called before starting a new one)."""
    supabase = get_supabase_client()
    if not supabase:
        return 0

    open_rows = supabase.table(TABLE).select('id, last_seen_at').eq(
        'host_name', host_name
    ).eq('device_id', device_id).is_('ended_at', 'null').execute()

    closed = 0
    for row in (open_rows.data or []):
        supabase.table(TABLE).update({
            'ended_at': row['last_seen_at'],
            'end_reason': 'dangling',
        }).eq('id', row['id']).is_('ended_at', 'null').execute()
        closed += 1
    if closed:
        print(f"[@device_control_sessions_db] 🧹 Closed {closed} dangling session(s) for {host_name}:{device_id}")
    return closed


def sweep_stale_sessions(older_than_seconds: int) -> int:
    """Close open sessions whose last_seen_at is older than the threshold.

    Safety across multiple backend_servers sharing this table: the threshold
    must exceed the script-lock max-age ceiling — any legitimately live session
    on ANY server is either heartbeating (manual) or younger than that ceiling
    (script/deployment), so rows older than it are guaranteed dead.
    """
    supabase = get_supabase_client()
    if not supabase:
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()
    stale = supabase.table(TABLE).select('id, last_seen_at').is_(
        'ended_at', 'null'
    ).lt('last_seen_at', cutoff).execute()

    closed = 0
    for row in (stale.data or []):
        supabase.table(TABLE).update({
            'ended_at': row['last_seen_at'],
            'end_reason': 'stale_sweep',
        }).eq('id', row['id']).is_('ended_at', 'null').execute()
        closed += 1
    if closed:
        print(f"[@device_control_sessions_db] 🧹 Stale-swept {closed} session(s) older than {older_than_seconds}s")
    return closed
