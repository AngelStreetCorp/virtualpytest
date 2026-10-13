"""Saved custom reports (TASK-42) — private to their creator within a team.

Every read, update and delete filters on BOTH ``team_id`` and ``created_by``:
another member of the same team cannot read, change or delete the report, and
an id from another team never matches. The filter document is validated by the
server (``services/analytics/report_query.py``) on save, on load and on execute.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.database.run_rpc import get_supabase, normalize_row

_UUID_KEYS = ('id', 'team_id')
_JSON_KEYS = ('filter', 'columns', 'chart')


def create_report(team_id: str, created_by: str, *, name: str, schema_version: int,
                  filter_doc: Dict[str, Any], columns: List[str], chart: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        'team_id': team_id,
        'created_by': created_by,
        'name': name,
        'schema_version': schema_version,
        'filter': filter_doc,
        'columns': columns,
        'chart': chart,
    }
    result = get_supabase().table('custom_reports').insert(row).execute()
    return normalize_row(result.data[0], _UUID_KEYS, _JSON_KEYS)


def list_reports(team_id: str, created_by: str, limit: int = 100) -> List[Dict[str, Any]]:
    result = (get_supabase().table('custom_reports').select('*')
              .eq('team_id', team_id).eq('created_by', created_by)
              .order('updated_at', desc=True).limit(limit).execute())
    return [normalize_row(r, _UUID_KEYS, _JSON_KEYS) for r in (result.data or [])]


def get_report(team_id: str, created_by: str, report_id: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table('custom_reports').select('*')
              .eq('team_id', team_id).eq('created_by', created_by).eq('id', report_id)
              .limit(1).execute())
    rows = result.data or []
    return normalize_row(rows[0], _UUID_KEYS, _JSON_KEYS) if rows else None


def update_report(team_id: str, created_by: str, report_id: str,
                  changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = dict(changes)
    payload['updated_at'] = datetime.now(timezone.utc).isoformat()
    result = (get_supabase().table('custom_reports').update(payload)
              .eq('team_id', team_id).eq('created_by', created_by).eq('id', report_id)
              .execute())
    rows = result.data or []
    return normalize_row(rows[0], _UUID_KEYS, _JSON_KEYS) if rows else None


def delete_report(team_id: str, created_by: str, report_id: str) -> bool:
    result = (get_supabase().table('custom_reports').delete()
              .eq('team_id', team_id).eq('created_by', created_by).eq('id', report_id)
              .execute())
    return bool(result.data)
