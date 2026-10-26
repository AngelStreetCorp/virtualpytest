"""Custom pages (TASK-139): saved block layouts, private to the owner unless shared.

Every query filters on ``team_id``. Who may read or write a page (owner, named share, team visibility) is
decided one level up in ``backend_server/src/services/custom_pages/service.py``; this module only stores.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.src.lib.database.run_rpc import get_supabase, normalize_row

_UUID_KEYS = ('id', 'team_id')
_JSON_KEYS = ('definition',)


def _norm(row: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_row(row, _UUID_KEYS, _JSON_KEYS)


def create_page(team_id: str, owner_id: str, *, title: str, schema_version: int,
                definition: Dict[str, Any], status: str) -> Dict[str, Any]:
    row = {'team_id': team_id, 'owner_id': owner_id, 'title': title, 'schema_version': schema_version,
           'definition': definition, 'status': status, 'visibility': 'private'}
    return _norm(get_supabase().table('custom_pages').insert(row).execute().data[0])


def get_page(team_id: str, page_id: str) -> Optional[Dict[str, Any]]:
    rows = (get_supabase().table('custom_pages').select('*')
            .eq('team_id', team_id).eq('id', page_id).limit(1).execute().data or [])
    return _norm(rows[0]) if rows else None


def list_visible_pages(team_id: str, user_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Pages the user owns, pages shared with them by name and saved pages visible to the whole team."""
    sb = get_supabase()
    owned = (sb.table('custom_pages').select('*').eq('team_id', team_id).eq('owner_id', user_id)
             .order('updated_at', desc=True).limit(limit).execute().data or [])
    shared_ids = [r['page_id'] for r in (sb.table('custom_page_shares').select('page_id')
                                         .eq('team_id', team_id).eq('user_id', user_id).execute().data or [])]
    shared = (sb.table('custom_pages').select('*').eq('team_id', team_id).eq('status', 'saved')
              .in_('id', shared_ids).execute().data or []) if shared_ids else []
    team_wide = (sb.table('custom_pages').select('*').eq('team_id', team_id).eq('status', 'saved')
                 .eq('visibility', 'team').order('updated_at', desc=True).limit(limit).execute().data or [])
    merged: Dict[str, Dict[str, Any]] = {}
    for row in [*owned, *shared, *team_wide]:
        merged.setdefault(str(row['id']), row)
    rows = sorted(merged.values(), key=lambda r: r.get('updated_at') or '', reverse=True)
    return [_norm(r) for r in rows[:limit]]


def update_page(team_id: str, page_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = dict(changes)
    payload['updated_at'] = datetime.now(timezone.utc).isoformat()
    rows = (get_supabase().table('custom_pages').update(payload)
            .eq('team_id', team_id).eq('id', page_id).execute().data or [])
    return _norm(rows[0]) if rows else None


def delete_page(team_id: str, page_id: str) -> bool:
    return bool(get_supabase().table('custom_pages').delete()
                .eq('team_id', team_id).eq('id', page_id).execute().data)


def get_share(team_id: str, page_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    rows = (get_supabase().table('custom_page_shares').select('*').eq('team_id', team_id)
            .eq('page_id', page_id).eq('user_id', user_id).limit(1).execute().data or [])
    return rows[0] if rows else None


def list_shares(team_id: str, page_id: str) -> List[Dict[str, Any]]:
    return (get_supabase().table('custom_page_shares').select('*').eq('team_id', team_id)
            .eq('page_id', page_id).order('created_at').execute().data or [])


def replace_shares(team_id: str, page_id: str, shares: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Make `shares` ([{user_id, can_edit}]) the complete share list of the page."""
    sb = get_supabase()
    sb.table('custom_page_shares').delete().eq('team_id', team_id).eq('page_id', page_id).execute()
    if shares:
        sb.table('custom_page_shares').insert(
            [{'page_id': page_id, 'team_id': team_id, 'user_id': s['user_id'], 'can_edit': bool(s['can_edit'])}
             for s in shares]).execute()
    return list_shares(team_id, page_id)
