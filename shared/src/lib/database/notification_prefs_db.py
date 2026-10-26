"""
Notification Preferences Database Operations (TASK-145)

One row = one category's channels at one scope (team / workspace / project / user).
Every query filters by team_id. Non-user rows have user_id '' ; a user row has the user's id.
See setup/db/schema/075_notification_prefs.sql and docs/agent/platform/NOTIFICATIONS.md.
"""

from typing import Dict, List

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'notification_prefs'
COLUMNS = 'scope_type,scope_id,user_id,category,bell,toast,email,min_severity,muted_until,locked'


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def list_prefs(team_id: str, user_id: str) -> List[Dict]:
    """The team's shared rows (team / workspace / project) plus this user's own rows."""
    result = get_supabase().table(TABLE)\
        .select(COLUMNS)\
        .eq('team_id', team_id)\
        .in_('user_id', ['', user_id])\
        .execute()
    return result.data or []


def upsert_pref(team_id: str, row: Dict) -> None:
    """Create or replace one row; the key is (team_id, scope_type, scope_id, user_id, category)."""
    get_supabase().table(TABLE).upsert(
        {**row, 'team_id': team_id},
        on_conflict='team_id,scope_type,scope_id,user_id,category',
    ).execute()


def delete_pref(team_id: str, scope_type: str, scope_id: str, user_id: str, category: str) -> None:
    """Drop one row, so the category inherits from the next level again. Idempotent."""
    get_supabase().table(TABLE).delete()\
        .eq('team_id', team_id)\
        .eq('scope_type', scope_type)\
        .eq('scope_id', scope_id)\
        .eq('user_id', user_id)\
        .eq('category', category)\
        .execute()
