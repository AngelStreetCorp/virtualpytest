"""
Library visibility database operations.

Visibility is visible-by-default: a missing row means the item is shown.
Hidden items are stored explicitly with is_visible = false.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from shared.src.lib.utils.supabase_utils import get_supabase_client

VALID_ENTITY_TYPES = {'script', 'testcase', 'campaign'}


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _validate_entity_type(entity_type: str) -> str:
    normalized = (entity_type or '').strip().lower()
    if normalized not in VALID_ENTITY_TYPES:
        raise ValueError(f'Invalid entity_type: {entity_type}')
    return normalized


def list_library_visibility(team_id: str, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """List stored visibility overrides for a team."""
    supabase = get_supabase()
    if not supabase or not team_id:
        return []

    try:
        query = (
            supabase.table('library_visibility')
            .select('id,team_id,entity_type,entity_key,is_visible,updated_at,updated_by')
            .eq('team_id', team_id)
        )

        if entity_type:
            query = query.eq('entity_type', _validate_entity_type(entity_type))

        result = query.order('entity_type').order('entity_key').execute()
        items = result.data if result.data else []
        for item in items:
            item['id'] = str(item['id'])
            item['team_id'] = str(item['team_id'])
        return items
    except Exception as e:
        print(f'[@library_visibility_db] ERROR listing visibility rules: {e}')
        return []


def list_hidden_library_keys(team_id: str, entity_type: str) -> Set[str]:
    """Return the hidden entity keys for a team and entity type."""
    supabase = get_supabase()
    if not supabase or not team_id:
        return set()

    try:
        normalized_type = _validate_entity_type(entity_type)
        result = (
            supabase.table('library_visibility')
            .select('entity_key')
            .eq('team_id', team_id)
            .eq('entity_type', normalized_type)
            .eq('is_visible', False)
            .execute()
        )
        return {row['entity_key'] for row in (result.data or []) if row.get('entity_key')}
    except Exception as e:
        print(f'[@library_visibility_db] ERROR listing hidden keys: {e}')
        return set()


def hide_library_item(team_id: str, entity_type: str, entity_key: str, updated_by: Optional[str] = None) -> bool:
    """Hide a library item for a team."""
    supabase = get_supabase()
    if not supabase or not team_id or not entity_key:
        return False

    try:
        normalized_type = _validate_entity_type(entity_type)
        payload = {
            'team_id': team_id,
            'entity_type': normalized_type,
            'entity_key': entity_key,
            'is_visible': False,
            'updated_by': updated_by,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        existing_result = (
            supabase.table('library_visibility')
            .select('id')
            .eq('team_id', team_id)
            .eq('entity_type', normalized_type)
            .eq('entity_key', entity_key)
            .execute()
        )

        if existing_result.data:
            result = (
                supabase.table('library_visibility')
                .update({
                    'is_visible': False,
                    'updated_by': updated_by,
                    'updated_at': payload['updated_at'],
                })
                .eq('team_id', team_id)
                .eq('entity_type', normalized_type)
                .eq('entity_key', entity_key)
                .execute()
            )
        else:
            result = (
                supabase.table('library_visibility')
                .insert(payload)
                .execute()
            )

        return bool(result.data is not None)
    except Exception as e:
        print(f'[@library_visibility_db] ERROR hiding item: {e}')
        return False


def show_library_item(team_id: str, entity_type: str, entity_key: str) -> bool:
    """Show a library item by deleting any hidden override."""
    supabase = get_supabase()
    if not supabase or not team_id or not entity_key:
        return False

    try:
        (
            supabase.table('library_visibility')
            .delete()
            .eq('team_id', team_id)
            .eq('entity_type', _validate_entity_type(entity_type))
            .eq('entity_key', entity_key)
            .execute()
        )
        return True
    except Exception as e:
        print(f'[@library_visibility_db] ERROR showing item: {e}')
        return False
