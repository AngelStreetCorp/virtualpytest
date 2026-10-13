"""Test-result defects and their evidence links (TASK-42).

Local-first: a defect is created locally; a Jira push is a separate explicit
action whose durable state lives in ``defect_jira_pushes`` (see
``rm_claim_defect_jira_push`` and friends). Nothing here ever writes
``script_results`` — resolving or closing a defect leaves discard, verdict and
evidence untouched.

Every query filters by ``team_id``. Evidence scope (registered hosts /
workspace) is enforced by the caller, which passes the allowed host list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from shared.src.lib.database.run_rpc import call_rpc, get_supabase, normalize_row

DEFECT_STATUSES = ('open', 'in_progress', 'resolved', 'closed')
DEFECT_SEVERITIES = ('low', 'medium', 'high', 'critical')
DEFECT_INTEGRATIONS = ('local', 'jira')
DEFECT_SORTS = ('updated_at', 'created_at', 'severity', 'status')

_UUID_KEYS = ('id', 'team_id')
_EVIDENCE_COLUMNS = (
    'id, script_name, script_type, userinterface_name, environment, host_name, '
    'device_name, success, execution_time_ms, started_at, completed_at, discard'
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_defect(team_id: str, *, title: str, description: Optional[str], severity: str,
                  assignee: Optional[str], created_by: str) -> Dict[str, Any]:
    row = {
        'team_id': team_id,
        'title': title,
        'description': description,
        'severity': severity,
        'status': 'open',
        'assignee': assignee,
        'created_by': created_by,
        'integration': 'local',
    }
    result = get_supabase().table('defects').insert(row).execute()
    return normalize_row(result.data[0], _UUID_KEYS)


def list_defects(team_id: str, *, status: Optional[str] = None, severity: Optional[str] = None,
                 integration: Optional[str] = None, script_result_id: Optional[str] = None,
                 limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    supabase = get_supabase()
    query = supabase.table('defects').select('*', count='exact').eq('team_id', team_id)
    if script_result_id:
        links = (supabase.table('defect_script_results').select('defect_id')
                 .eq('team_id', team_id).eq('script_result_id', script_result_id)
                 .limit(500).execute()).data or []
        defect_ids = sorted({str(link['defect_id']) for link in links})
        if not defect_ids:
            return {'items': [], 'total': 0}
        query = query.in_('id', defect_ids)
    if status:
        query = query.eq('status', status)
    if severity:
        query = query.eq('severity', severity)
    if integration:
        query = query.eq('integration', integration)
    result = (query.order('updated_at', desc=True).order('id', desc=True)
              .range(offset, offset + limit - 1).execute())
    return {
        'items': [normalize_row(r, _UUID_KEYS) for r in (result.data or [])],
        'total': getattr(result, 'count', None),
    }


def get_defect(team_id: str, defect_id: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table('defects').select('*')
              .eq('team_id', team_id).eq('id', defect_id).limit(1).execute())
    rows = result.data or []
    return normalize_row(rows[0], _UUID_KEYS) if rows else None


def update_defect(team_id: str, defect_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Apply already-validated field changes (title/description/severity/status/assignee)."""
    payload = dict(changes)
    payload['updated_at'] = _now()
    result = (get_supabase().table('defects').update(payload)
              .eq('team_id', team_id).eq('id', defect_id).execute())
    rows = result.data or []
    return normalize_row(rows[0], _UUID_KEYS) if rows else None


def apply_jira_refresh(team_id: str, defect_id: str, *, status: str, external_status: str,
                       external_updated_at: str) -> bool:
    """Write a refreshed Jira status only if it is newer than the last one applied.

    The ``external_updated_at`` guard makes the write idempotent and tolerant of
    out-of-order refreshes: an older Jira snapshot never overwrites a newer one.
    """
    supabase = get_supabase()
    query = (supabase.table('defects')
             .update({
                 'status': status,
                 'external_status': external_status,
                 'external_updated_at': external_updated_at,
                 'updated_at': _now(),
             })
             .eq('team_id', team_id).eq('id', defect_id).eq('integration', 'jira')
             .or_(f'external_updated_at.is.null,external_updated_at.lt.{external_updated_at}'))
    result = query.execute()
    return bool(result.data)


def link_evidence(team_id: str, defect_id: str, script_result_ids: Sequence[str],
                  linked_by: str) -> int:
    """Link script results (already scope-checked by the caller). Idempotent."""
    rows = [{
        'team_id': team_id,
        'defect_id': defect_id,
        'script_result_id': sid,
        'linked_by': linked_by,
    } for sid in script_result_ids]
    if not rows:
        return 0
    result = (get_supabase().table('defect_script_results')
              .upsert(rows, on_conflict='team_id,defect_id,script_result_id', ignore_duplicates=True)
              .execute())
    return len(result.data or [])


def unlink_evidence(team_id: str, defect_id: str, script_result_id: str) -> bool:
    result = (get_supabase().table('defect_script_results').delete()
              .eq('team_id', team_id).eq('defect_id', defect_id)
              .eq('script_result_id', script_result_id).execute())
    return bool(result.data)


def list_evidence(team_id: str, defect_id: str, host_names: Sequence[str],
                  limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Linked script results visible from this server (host scope applied in the query)."""
    if not host_names:
        return {'items': [], 'total': 0}
    result = (get_supabase().table('defect_script_results')
              .select(f'script_result_id, created_at, linked_by, '
                      f'script_results!inner({_EVIDENCE_COLUMNS})', count='exact')
              .eq('team_id', team_id).eq('defect_id', defect_id)
              .in_('script_results.host_name', list(host_names))
              .order('created_at', desc=True)
              .range(offset, offset + limit - 1).execute())
    items: List[Dict[str, Any]] = []
    for link in result.data or []:
        sr = link.get('script_results')
        if isinstance(sr, list):
            sr = sr[0] if sr else None
        if not sr:
            continue
        sr = normalize_row(dict(sr), ('id',))
        sr['linked_at'] = link.get('created_at')
        sr['linked_by'] = link.get('linked_by')
        items.append(sr)
    return {'items': items, 'total': getattr(result, 'count', None)}


def get_jira_push(team_id: str, defect_id: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table('defect_jira_pushes')
              .select('instance_id, project_key, correlation_label, state, attempts, lease_until, '
                      'external_key, external_url, last_error, updated_at')
              .eq('team_id', team_id).eq('defect_id', defect_id).limit(1).execute())
    rows = result.data or []
    return rows[0] if rows else None


def claim_jira_push(team_id: str, defect_id: str, instance_id: str, project_key: str,
                    lease_seconds: int) -> Dict[str, Any]:
    return call_rpc('rm_claim_defect_jira_push', {
        'p_team_id': team_id,
        'p_defect_id': defect_id,
        'p_instance_id': instance_id,
        'p_project_key': project_key,
        'p_lease_seconds': lease_seconds,
    }) or {}


def complete_jira_push(team_id: str, defect_id: str, external_key: str, external_url: str) -> bool:
    return bool(call_rpc('rm_complete_defect_jira_push', {
        'p_team_id': team_id,
        'p_defect_id': defect_id,
        'p_external_key': external_key,
        'p_external_url': external_url,
    }))


def fail_jira_push(team_id: str, defect_id: str, error: str, release_lease: bool) -> bool:
    return bool(call_rpc('rm_fail_defect_jira_push', {
        'p_team_id': team_id,
        'p_defect_id': defect_id,
        'p_error': error,
        'p_release_lease': release_lease,
    }))
