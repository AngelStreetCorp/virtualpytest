"""Read-only activity feed (TASK-127 G6): one list over the audit tables that already exist.

Sources: ``masterchief_audit`` (elevated operations), ``localize_verdicts`` (Localize
corrections and their undo) and ``audit_events`` (TASK-154: logins, API calls, device control, AI, cron). Nothing is recorded here; project link/tag changes only write a
log line today and have no table, so they are not part of the feed.

Every query filters by ``team_id``.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

PER_SOURCE_LIMIT = 500
logger = logging.getLogger(__name__)

# masterchief_audit.state -> (event label, tone)
_OP_STATES = {
    'proposed': ('Elevated op proposed', 'running'),
    'executing': ('Elevated op running', 'running'),
    'executed': ('Elevated op done', 'ok'),
    'failed': ('Elevated op failed', 'error'),
    'refused': ('Elevated op refused', 'error'),
}


def _actor_op(row: Dict[str, Any]) -> str:
    return row.get('requester_email') or row.get('requester_user_id') or ''


def masterchief_events(team_id: str, cutoff_iso: str) -> List[Dict[str, Any]]:
    res = get_supabase_client().table('masterchief_audit') \
        .select('id, requester_user_id, requester_email, op, host, state, result_summary, at') \
        .eq('team_id', team_id).gte('at', cutoff_iso) \
        .order('at', desc=True).limit(PER_SOURCE_LIMIT).execute()
    out = []
    for r in res.data or []:
        event, tone = _OP_STATES.get(r.get('state'), ('Elevated op', 'neutral'))
        target = ' · '.join(p for p in (str(r.get('op') or '').replace('_', ' '), r.get('host')) if p)
        out.append({'at': r['at'], 'event': event, 'tone': tone, 'target': target,
                    'details': r.get('result_summary') or '', 'actor': _actor_op(r),
                    'source': 'masterchief'})
    return out


def localize_events(team_id: str, cutoff_iso: str) -> List[Dict[str, Any]]:
    res = get_supabase_client().table('localize_verdicts') \
        .select('id, userinterface_name, action, wrong_node_label, true_node_label, '
                'created_by, created_at, undone_at, undone_by') \
        .eq('team_id', team_id).gte('created_at', cutoff_iso) \
        .order('created_at', desc=True).limit(PER_SOURCE_LIMIT).execute()
    out = []
    for r in res.data or []:
        ui = r.get('userinterface_name') or ''
        if r.get('action') == 'add_sample':
            node, details = r.get('true_node_label') or '', f"was {r.get('wrong_node_label') or 'unknown'}"
        else:
            node, details = r.get('wrong_node_label') or '', 'marked as unknown screen'
        target = f'{ui} / {node}' if node else ui
        out.append({'at': r['created_at'], 'event': 'Localize corrected', 'tone': 'running',
                    'target': target, 'details': details, 'actor': r.get('created_by') or '',
                    'source': 'localize'})
        if r.get('undone_at'):
            out.append({'at': r['undone_at'], 'event': 'Localize correction undone', 'tone': 'neutral',
                        'target': target, 'details': details, 'actor': r.get('undone_by') or '',
                        'source': 'localize'})
    return out


_AUDIT_LABELS = {'auth': 'Login', 'api': 'API call', 'control': 'Device control', 'ai': 'AI call',
                 'deploy': 'Deploy', 'test': 'Test run', 'admin': 'Admin action', 'system': 'System'}
_AUDIT_TONES = {'ok': 'ok', 'denied': 'error', 'error': 'error', 'refused': 'error'}


def _audit_actor(r: Dict[str, Any]) -> str:
    """Who called: name or id, then the kind (user, agent, service, cron...) and the role."""
    who = r.get('actor_email') or r.get('actor_id') or 'unknown'
    tags = [t for t in (r.get('actor_kind'), r.get('actor_role')) if t]
    return f"{who} ({', '.join(tags)})" if tags else who


def audit_events(team_id: str, cutoff_iso: str) -> List[Dict[str, Any]]:
    """TASK-154 audit_events rows: users, AI agents, hosts, cron jobs and service principals."""
    from shared.src.lib.database import audit_events_db
    out = []
    for r in audit_events_db.list_events(team_id, cutoff_iso, PER_SOURCE_LIMIT):
        meta = r.get('meta') or {}
        status = f" · {r['status_code']}" if r.get('status_code') else ''
        what = ' '.join(str(meta[k]) for k in ('command', 'key') if meta.get(k))
        where = '/'.join(str(meta[k]) for k in ('host_name', 'device_id') if meta.get(k))
        out.append({'at': r['at'], 'event': _AUDIT_LABELS.get(r.get('category'), 'Audit'),
                    'tone': _AUDIT_TONES.get(r.get('outcome'), 'neutral'),
                    'target': r.get('target') or r.get('action') or '',
                    'details': f"{r.get('action', '')}{status}" + (f" · {what}" if what else '') + (f" · {where}" if where else '')
                              + (f" · {meta['endpoint']}" if meta.get('endpoint') else ''),
                    'actor': _audit_actor(r),
                    'source': 'audit'})
    return out


def parse_since(value: Optional[str], default_days: int = 30) -> datetime:
    """`7d` / `24h` / an ISO date or datetime -> UTC datetime; capped to 90 days back."""
    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=90)
    since = now - timedelta(days=default_days)
    v = (value or '').strip()
    try:
        if v[-1:] == 'd' and v[:-1].isdigit():
            since = now - timedelta(days=int(v[:-1]))
        elif v[-1:] == 'h' and v[:-1].isdigit():
            since = now - timedelta(hours=int(v[:-1]))
        elif v:
            since = datetime.fromisoformat(v.replace('Z', '+00:00'))
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return max(since, floor)


def list_activity(team_id: str, *, q: str = '', event: str = '', actor: str = '',
                  since: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    """Unified rows newest first. `counts` / `actors` describe the rows that match q, actor and
    since, before the event filter, so the event dropdown can show a count per event."""
    cutoff = parse_since(since).isoformat()
    rows: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for name, source in (('masterchief', masterchief_events), ('localize', localize_events), ('audit', audit_events)):
        try:
            rows += source(team_id, cutoff)
        except Exception as e:  # a missing table (PGRST205) or any query error skips only that source
            logger.warning('[activity] source %s skipped: %s', name, e)
            skipped.append(name)
    rows = [r for r in rows if r['at'] >= cutoff]
    needle = (q or '').strip().lower()
    if needle:
        rows = [r for r in rows if needle in ' '.join(
            str(r[k]) for k in ('event', 'target', 'details', 'actor')).lower()]
    actors = sorted({r['actor'] for r in rows if r['actor']})
    if actor:
        rows = [r for r in rows if r['actor'] == actor]
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r['event']] = counts.get(r['event'], 0) + 1
    if event:
        rows = [r for r in rows if r['event'] == event]
    rows.sort(key=lambda r: r['at'], reverse=True)
    limit = max(1, min(1000, int(limit or 200)))
    return {'rows': rows[:limit], 'total': len(rows), 'counts': counts, 'actors': actors,
            'skipped_sources': skipped}
