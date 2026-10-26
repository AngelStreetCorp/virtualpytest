"""support_tickets: team-scoped index of helpdesk tickets (TASK-96).

The conversation lives in the helpdesk; this table only lets pages list a team's tickets and
show "N open tickets" on an entity. Every function filters by team_id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from features.zammad.lib.model import CLOSED_STATUSES
from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'support_tickets'


def get_supabase():
    return get_supabase_client()


def _normalize(row: Dict[str, Any]) -> Dict[str, Any]:
    for key in ('id', 'team_id'):
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


def insert_ticket(*, team_id: str, ticket_type: str, family: str, category: str,
                  target_id: Optional[str], target_label: Optional[str],
                  severity: Optional[str], frequency: str, priority: str,
                  title: str, status: str, external_provider: str, external_id: str,
                  external_number: Optional[str], created_by: str,
                  created_by_email: Optional[str]) -> Dict[str, Any]:
    row = {
        'team_id': team_id, 'ticket_type': ticket_type, 'family': family, 'category': category,
        'target_id': target_id, 'target_label': target_label, 'severity': severity, 'frequency': frequency,
        'priority': priority, 'title': title, 'status': status, 'external_provider': external_provider,
        'external_id': external_id, 'external_number': external_number,
        'created_by': created_by, 'created_by_email': created_by_email,
    }
    result = get_supabase().table(TABLE).insert(row).execute()
    return _normalize(result.data[0])


def _classified(query, ticket_type: Optional[str], family: Optional[str], severity: Optional[str]):
    for column, value in (('ticket_type', ticket_type), ('family', family), ('severity', severity)):
        if value:
            query = query.eq(column, value)
    return query


def list_tickets(team_id: str, *, status: Optional[str] = None, target_id: Optional[str] = None,
                 category: Optional[str] = None, ticket_type: Optional[str] = None,
                 family: Optional[str] = None, severity: Optional[str] = None,
                 created_by: Optional[str] = None,
                 project: Optional[Tuple[Set[str], Set[str]]] = None, since: Optional[str] = None,
                 limit: int = 100) -> List[Dict[str, Any]]:
    query = get_supabase().table(TABLE).select('*').eq('team_id', team_id)
    query = _classified(query, ticket_type, family, severity)
    if created_by:
        query = query.eq('created_by', created_by)
    if since:
        query = query.gte('created_at', since)
    if status:
        query = query.eq('status', status)
    if category:
        query = query.eq('category', category)
    if target_id:
        query = query.eq('target_id', target_id)
    # a project is applied in Python (its teams OR its people), so over-fetch before cutting to `limit`
    result = query.order('created_at', desc=True).limit(limit * 10 if project else limit).execute()
    rows = [_normalize(r) for r in (result.data or [])]
    return [r for r in rows if in_project(r, project)][:limit]


def in_project(row: Dict[str, Any], project: Optional[Tuple[Set[str], Set[str]]]) -> bool:
    """A project (workspace) is its teams and its people: no project = everything."""
    if project is None:
        return True
    teams, users = project
    return str(row.get('team_id')) in teams or str(row.get('created_by')) in users


def compute_stats(rows: List[Dict[str, Any]], since: Optional[str],
                  created_by: Optional[str] = None) -> Dict[str, Any]:
    """Counts over rows already scoped to a team (and user / workspace).

    opened = created in the period; closed = status closed | duplicate | wont_fix AND last updated in the period;
    total = every ticket in scope, whatever the period. ISO timestamps of one format compare as text.
    """
    def in_period(value: Optional[str]) -> bool:
        return since is None or (value is not None and str(value) >= since)

    users: Dict[str, str] = {}  # every person in the team/workspace scope, so the User filter keeps its options
    for r in rows:
        if r.get('created_by'):
            users[str(r['created_by'])] = r.get('created_by_email') or str(r['created_by'])
    if created_by:
        rows = [r for r in rows if r.get('created_by') == created_by]
    return {
        'opened': sum(1 for r in rows if in_period(r.get('created_at'))),
        'closed': sum(1 for r in rows if r.get('status') in CLOSED_STATUSES and in_period(r.get('updated_at'))),
        'total': len(rows),
        'users': [{'id': k, 'email': v} for k, v in sorted(users.items(), key=lambda kv: kv[1].lower())],
    }


def ticket_stats(team_id: str, *, since: Optional[str] = None, created_by: Optional[str] = None,
                 project: Optional[Tuple[Set[str], Set[str]]] = None, ticket_type: Optional[str] = None,
                 family: Optional[str] = None, severity: Optional[str] = None) -> Dict[str, Any]:
    query = _classified(get_supabase().table(TABLE).select('*').eq('team_id', team_id),
                        ticket_type, family, severity)
    rows = [r for r in (query.order('created_at', desc=True).limit(10000).execute().data or [])
            if in_project(r, project)]
    return compute_stats(rows, since, created_by)


def get_ticket(team_id: str, ticket_id: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table(TABLE).select('*').eq('team_id', team_id).eq('id', ticket_id)
              .limit(1).execute())
    return _normalize(result.data[0]) if result.data else None


def update_status(team_id: str, ticket_id: str, status: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table(TABLE).update({'status': status, 'updated_at': 'now()'})
              .eq('team_id', team_id).eq('id', ticket_id).execute())
    return _normalize(result.data[0]) if result.data else None
