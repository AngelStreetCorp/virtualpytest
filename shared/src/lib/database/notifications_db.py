"""
Notification History Database Operations (TASK-145 follow-up)

One row = one notification of one user (the bell / Notifications page history, newest 200 per user).
Every query filters by team_id AND user_id: a user only ever sees their own rows.
`dismissed` rows are tombstones, so another browser's old local cache cannot bring them back.
See setup/db/schema/076_notifications_history.sql and docs/agent/platform/NOTIFICATIONS.md.
"""

from typing import Dict, List

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'notifications'
COLUMNS = 'id,category,severity,message,vars,to_path,scope,ts,read,dismissed,resolved_at'
KEEP = 200


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def list_notifications(team_id: str, user_id: str) -> List[Dict]:
    """The user's newest rows (dismissed tombstones included), newest first."""
    result = get_supabase().table(TABLE)\
        .select(COLUMNS)\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)\
        .order('ts', desc=True)\
        .limit(KEEP)\
        .execute()
    return result.data or []


def upsert_notifications(team_id: str, user_id: str, rows: List[Dict]) -> None:
    """Create or replace rows by (team_id, user_id, id), then trim the user's history to the newest KEEP."""
    if not rows:
        return
    get_supabase().table(TABLE).upsert(
        [{**r, 'team_id': team_id, 'user_id': user_id} for r in rows],
        on_conflict='team_id,user_id,id',
    ).execute()
    _trim(team_id, user_id)


def _trim(team_id: str, user_id: str) -> None:
    result = get_supabase().table(TABLE)\
        .select('id')\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)\
        .order('ts', desc=True)\
        .range(KEEP, KEEP + 999)\
        .execute()
    stale = [r['id'] for r in (result.data or [])]
    if stale:
        get_supabase().table(TABLE).delete()\
            .eq('team_id', team_id)\
            .eq('user_id', user_id)\
            .in_('id', stale)\
            .execute()


def mark_read(team_id: str, user_id: str, notification_id: str = None) -> None:
    """Mark one notification (or, without an id, all of the user's) read."""
    q = get_supabase().table(TABLE).update({'read': True}).eq('team_id', team_id).eq('user_id', user_id)
    if notification_id:
        q = q.eq('id', notification_id)
    q.execute()


def dismiss(team_id: str, user_id: str, notification_id: str = None) -> None:
    """Dismiss one notification (or, without an id, all of the user's). Rows stay as tombstones."""
    q = get_supabase().table(TABLE).update({'dismissed': True, 'read': True}).eq('team_id', team_id).eq('user_id', user_id)
    if notification_id:
        q = q.eq('id', notification_id)
    q.execute()


def purge_older_than(team_id: str, user_id: str, now_ms: int, grace_ms: int, max_age_ms: int) -> int:
    """Drop the user's rows that have outlived the grace window (resolved) or the rolling window (any).
    Returns how many rows were deleted. Idempotent. Called when the bell purges so server and local
    stay aligned.
    """
    sb = get_supabase()
    rows = sb.table(TABLE).select('id,ts,resolved_at').eq('team_id', team_id).eq('user_id', user_id).execute().data or []
    stale = [
        r['id'] for r in rows
        if (r.get('resolved_at') is not None and now_ms - int(r['resolved_at']) >= grace_ms)
        or now_ms - int(r['ts']) >= max_age_ms
    ]
    if not stale:
        return 0
    sb.table(TABLE).delete().eq('team_id', team_id).eq('user_id', user_id).in_('id', stale).execute()
    return len(stale)
