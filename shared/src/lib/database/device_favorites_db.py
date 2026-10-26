"""
Device Favorites Database Operations (TASK-99)

A favorite is one device a user starred, per team. The key is
(team_id, user_id, host_name, device_id): host_name is part of it because device ids
collide across servers. Every query filters by team_id AND user_id.
See setup/db/schema/069_device_favorites.sql.
"""

from typing import Dict, List

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'device_favorites'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def list_favorites(team_id: str, user_id: str) -> List[Dict]:
    """The user's starred devices in the team, as [{host_name, device_id}]."""
    result = get_supabase().table(TABLE)\
        .select('host_name,device_id')\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)\
        .order('created_at')\
        .execute()
    return result.data or []


def add_favorite(team_id: str, user_id: str, host_name: str, device_id: str) -> None:
    """Star a device. Idempotent: starring twice keeps one row."""
    get_supabase().table(TABLE).upsert(
        {'team_id': team_id, 'user_id': user_id, 'host_name': host_name, 'device_id': device_id},
        on_conflict='team_id,user_id,host_name,device_id',
    ).execute()


def remove_favorite(team_id: str, user_id: str, host_name: str, device_id: str) -> None:
    """Unstar a device. Idempotent: removing a device that is not starred is not an error."""
    get_supabase().table(TABLE).delete()\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)\
        .eq('host_name', host_name)\
        .eq('device_id', device_id)\
        .execute()
