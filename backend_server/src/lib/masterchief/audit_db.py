"""Audit table access for masterchief.

TASK-71. The only table masterchief may write to. Reads are team-scoped;
`scope='platform'` is the documented exception for admin reads across teams
(CONTRACTS #29 pending). All writes are service-role (the table has RLS that
locks out anon and authenticated).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

from .redaction import redact_params, redact_result

logger = logging.getLogger(__name__)

VALID_STATES = {'proposed', 'executing', 'executed', 'failed', 'refused'}


def _supabase():
    return get_supabase_client()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_audit_row(*, team_id: str, requester_user_id: str, requester_email: str,
                     requester_role: str, op: str, params: Any, host: Optional[str],
                     state: str, session_id: Optional[str] = None,
                     trace_id: Optional[str] = None) -> Dict[str, Any]:
    """Insert one audit row. Caller is responsible for choosing a valid state.

    The row is returned with the freshly assigned `id` and `at`.
    """
    if state not in VALID_STATES:
        raise ValueError(f"invalid masterchief audit state: {state!r}")
    if not team_id:
        raise ValueError("masterchief audit requires team_id")
    if not requester_user_id:
        raise ValueError("masterchief audit requires requester_user_id")
    row = {
        'team_id': team_id,
        'requester_user_id': requester_user_id,
        'requester_email': requester_email or '',
        'requester_role': requester_role or 'unknown',
        'op': op,
        'params_redacted': redact_params(params),
        'host': host or None,
        'state': state,
        'session_id': session_id or None,
        'trace_id': trace_id or None,
        'at': _now_iso(),
    }
    res = _supabase().table('masterchief_audit').insert(row).execute()
    data = (res.data or [])
    if not data:
        raise RuntimeError("masterchief_audit insert returned no rows")
    return dict(data[0])


def update_audit_state(audit_id: str, *, team_id: str, state: str,
                       result_summary: Optional[str] = None,
                       duration_ms: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Update the state (and optional result/duration) of a previously inserted row.

    The team_id filter is the same one every query uses (CONTRACTS.md).
    Returns the updated row, or None if no row matched.
    """
    if state not in VALID_STATES:
        raise ValueError(f"invalid masterchief audit state: {state!r}")
    patch: Dict[str, Any] = {'state': state}
    if result_summary is not None:
        patch['result_summary'] = redact_result(result_summary)
    if duration_ms is not None:
        patch['duration_ms'] = int(duration_ms)
    res = _supabase().table('masterchief_audit') \
        .update(patch) \
        .eq('id', audit_id) \
        .eq('team_id', team_id) \
        .execute()
    data = (res.data or [])
    return dict(data[0]) if data else None


def get_audit_row(audit_id: str, *, team_id: str) -> Optional[Dict[str, Any]]:
    res = _supabase().table('masterchief_audit') \
        .select('id, team_id, requester_user_id, requester_email, requester_role, op, '
                'params_redacted, host, state, result_summary, duration_ms, trace_id, '
                'session_id, at') \
        .eq('id', audit_id) \
        .eq('team_id', team_id) \
        .limit(1) \
        .execute()
    data = (res.data or [])
    return dict(data[0]) if data else None


def list_audit_rows(*, team_id: str, scope: str = 'team', state: Optional[str] = None,
                    op: Optional[str] = None, days: int = 30, limit: int = 50,
                    offset: int = 0) -> Dict[str, Any]:
    """Paginated audit rows for the caller's team (or all teams when scope=platform).

    scope='platform' is admin-only and is the documented exception to the
    team_id filter (CONTRACTS #29). The caller enforces that; this function
    just selects.
    """
    limit = max(1, min(200, int(limit or 50)))
    offset = max(0, min(10_000, int(offset or 0)))
    days = max(1, min(90, int(days or 30)))
    q = _supabase().table('masterchief_audit') \
        .select('id, team_id, requester_user_id, requester_email, requester_role, op, '
                'params_redacted, host, state, result_summary, duration_ms, trace_id, '
                'session_id, at', count='exact')
    if scope != 'platform':
        q = q.eq('team_id', team_id)
    if state:
        q = q.eq('state', state)
    if op:
        q = q.eq('op', op)
    # The `at` column is timestamptz; Supabase filter `gte` works as ISO string.
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = q.gte('at', cutoff)
    q = q.order('at', desc=True).range(offset, offset + limit - 1)
    res = q.execute()
    rows = [dict(r) for r in (res.data or [])]
    total = getattr(res, 'count', None)
    return {'rows': rows, 'total': total, 'limit': limit, 'offset': offset, 'days': days}


def count_open_for_user(*, team_id: str, user_id: str, op: str,
                        since_minutes: int = 60) -> int:
    """Count in-flight audit rows for one user+op within the last N minutes.

    Used by the rate limiter. The query is bounded: at most `since_minutes` of
    history and filtered by state in {proposed, executing}.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
    res = _supabase().table('masterchief_audit') \
        .select('id', count='exact') \
        .eq('team_id', team_id) \
        .eq('requester_user_id', user_id) \
        .eq('op', op) \
        .in_('state', ['proposed', 'executing']) \
        .gte('at', cutoff) \
        .execute()
    return int(getattr(res, 'count', 0) or 0)
