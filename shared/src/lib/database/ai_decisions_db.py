"""
AI Decisions Database Operations (TASK-38 §5)

One row per Jev-style decision call (``shared/src/lib/ai/decisions``): the state and
questions sent, the typed answers with probabilities, cost, and — once known — the
checked outcome. It is the ground truth for decision thresholds and the fine-tuning
set for a local decision model. Every query filters by ``team_id``.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'ai_decisions'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _json_field(val):
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def insert_decision(row: Dict[str, Any]) -> Optional[str]:
    """Insert one decision row. ``row`` must carry ``team_id``. Returns the id or None."""
    if not row.get('team_id'):
        print("[@db:ai_decisions:insert_decision] refused: no team_id")
        return None
    try:
        result = get_supabase().table(TABLE).insert(row).execute()
        return str(result.data[0]['id']) if result.data else None
    except Exception as e:
        print(f"[@db:ai_decisions:insert_decision] Error: {e}")
        return None


def set_outcome(decision_id: str, team_id: str, outcome: Dict[str, Any]) -> bool:
    """Attach the checked outcome to a decision of ``team_id``."""
    try:
        result = (get_supabase().table(TABLE)
                  .update({'outcome': outcome, 'outcome_at': datetime.now(timezone.utc).isoformat()})
                  .eq('id', decision_id)
                  .eq('team_id', team_id)
                  .execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@db:ai_decisions:set_outcome] Error: {e}")
        return False


def set_refs(decision_id: str, team_id: str, refs: Dict[str, Any]) -> bool:
    """Replace the refs of a decision of ``team_id`` (today's answer known only after the call)."""
    try:
        result = (get_supabase().table(TABLE).update({'refs': refs})
                  .eq('id', decision_id).eq('team_id', team_id).execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@db:ai_decisions:set_refs] Error: {e}")
        return False


def prune_decisions(team_id: str, usage_key: str, older_than_days: int) -> int:
    """Delete that team's rows of ``usage_key`` with ``created_at`` older than now - N days.

    ``team_id`` and ``usage_key`` are required (an empty value is refused, returns 0).
    Returns the deleted count, or 0 on error — never raises.
    """
    if not team_id or not usage_key:
        print("[@db:ai_decisions:prune_decisions] refused: team_id and usage_key are required")
        return 0
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=int(older_than_days))).isoformat()
        result = (get_supabase().table(TABLE).delete()
                  .eq('team_id', team_id)
                  .eq('usage_key', usage_key)
                  .lt('created_at', cutoff)
                  .execute())
        if not result.data:
            return 0
        return len(result.data)
    except Exception as e:
        print(f"[@db:ai_decisions:prune_decisions] Error: {e}")
        return 0


def list_decisions(team_id: str, usage_key: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Newest decisions of ``team_id`` (optionally one usage)."""
    try:
        query = get_supabase().table(TABLE).select('*').eq('team_id', team_id)
        if usage_key:
            query = query.eq('usage_key', usage_key)
        rows = query.order('created_at', desc=True).limit(limit).execute().data or []
    except Exception as e:
        print(f"[@db:ai_decisions:list_decisions] Error: {e}")
        return []
    for row in rows:
        row['id'] = str(row['id'])
        for key in ('state', 'questions', 'answers', 'outcome', 'refs'):
            row[key] = _json_field(row.get(key))
    return rows


LIST_COLUMNS = ('id,team_id,created_at,usage_key,request_id,profile,model,questions,answers,ok,error,ms,'
                'tokens_in,cost,refs,outcome,outcome_at')
MAX_LIMIT = 500
_REF_KEY = re.compile(r'^[A-Za-z0-9_]{1,40}$')
_SUMMARY_PAGE = 1000
_SUMMARY_MAX_ROWS = 20000
SUMMARY_DAYS = 14


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return escaped + '*'


def _apply_filters(query, usage: Optional[str], since: Optional[str], until: Optional[str],
                   ok: Optional[bool], has_outcome: Optional[bool], refs: Optional[Dict[str, str]]):
    if usage:
        # A trailing dot is a prefix ("text.decision." = every child); anything else is exact.
        query = query.like('usage_key', _like_prefix(usage)) if usage.endswith('.') else query.eq('usage_key', usage)
    if since:
        query = query.gte('created_at', since)
    if until:
        query = query.lt('created_at', until)
    if ok is not None:
        query = query.eq('ok', ok)
    if has_outcome is True:
        query = query.not_.is_('outcome_at', 'null')
    elif has_outcome is False:
        query = query.is_('outcome_at', 'null')
    for key, value in (refs or {}).items():
        if not _REF_KEY.match(key):
            raise ValueError(f'bad refs key: {key!r}')
        query = query.eq(f'refs->>{key}', str(value))
    return query


def _decode(row: Dict[str, Any]) -> Dict[str, Any]:
    row['id'] = str(row['id'])
    for key in ('state', 'questions', 'answers', 'outcome', 'refs'):
        if key in row:
            row[key] = _json_field(row[key])
    return row


def query_decisions(team_id: str, usage: Optional[str] = None, since: Optional[str] = None,
                    until: Optional[str] = None, ok: Optional[bool] = None,
                    has_outcome: Optional[bool] = None, refs: Optional[Dict[str, str]] = None,
                    include_state: bool = False, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    """Filtered decisions of ``team_id``, newest first. ``state`` only with ``include_state``.

    ``usage`` ending in ``.`` is a prefix, else exact. ``refs`` filters ``refs->>key == value``.
    Raises on a database error (the route reports it) — an empty list means no match.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    columns = LIST_COLUMNS + (',state' if include_state else '')
    query = get_supabase().table(TABLE).select(columns).eq('team_id', team_id)
    query = _apply_filters(query, usage, since, until, ok, has_outcome, refs)
    rows = query.order('created_at', desc=True).range(offset, offset + limit - 1).execute().data or []
    return [_decode(r) for r in rows]


def summarize_decisions(team_id: str, since: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Per usage_key: calls, failed, cost, last_at, with/without outcome, calls per day (last 14 UTC days)."""
    now = now or datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    while len(rows) < _SUMMARY_MAX_ROWS:
        query = (get_supabase().table(TABLE).select('usage_key,ok,cost,created_at,outcome_at')
                 .eq('team_id', team_id))
        if since:
            query = query.gte('created_at', since)
        page = (query.order('created_at', desc=True)
                .range(len(rows), len(rows) + _SUMMARY_PAGE - 1).execute().data or [])
        rows.extend(page)
        if len(page) < _SUMMARY_PAGE:
            break
    days = [(now - timedelta(days=i)).date().isoformat() for i in range(SUMMARY_DAYS - 1, -1, -1)]
    usages: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        u = usages.setdefault(r['usage_key'], {
            'usage_key': r['usage_key'], 'calls': 0, 'failed': 0, 'cost': 0.0, 'last_at': None,
            'with_outcome': 0, 'without_outcome': 0, 'per_day': {d: 0 for d in days}})
        u['calls'] += 1
        u['failed'] += 0 if r.get('ok') else 1
        u['cost'] += float(r.get('cost') or 0)
        created = r.get('created_at')
        if created and (u['last_at'] is None or created > u['last_at']):
            u['last_at'] = created
        u['with_outcome' if r.get('outcome_at') else 'without_outcome'] += 1
        day = (created or '')[:10]
        if day in u['per_day']:
            u['per_day'][day] += 1
    return {'since': since, 'days': days, 'truncated': len(rows) >= _SUMMARY_MAX_ROWS,
            'usages': sorted(usages.values(), key=lambda u: u['usage_key'])}
