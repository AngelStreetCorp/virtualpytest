"""
Executable Favorites Database Operations (TASK-100)

A favorite is one script, test case, virtual script or campaign a user starred, per team.
The key is (team_id, user_id, kind, item_id): kind is part of it because the id namespaces
differ (script file name, testcase uuid, virtual script name, campaign id).
Every query filters by team_id AND user_id. See setup/db/schema/070_executable_favorites.sql.
"""

from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'executable_favorites'
KINDS = ('script', 'testcase', 'virtual_script', 'campaign')


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def list_favorites(team_id: str, user_id: str, kind: Optional[str] = None) -> List[Dict]:
    """The user's starred executables in the team, as [{kind, item_id}], optionally one kind."""
    query = get_supabase().table(TABLE)\
        .select('kind,item_id')\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)
    if kind:
        query = query.eq('kind', kind)
    return query.order('created_at').execute().data or []


def add_favorite(team_id: str, user_id: str, kind: str, item_id: str) -> None:
    """Star an executable. Idempotent: starring twice keeps one row."""
    get_supabase().table(TABLE).upsert(
        {'team_id': team_id, 'user_id': user_id, 'kind': kind, 'item_id': item_id},
        on_conflict='team_id,user_id,kind,item_id',
    ).execute()


def remove_favorite(team_id: str, user_id: str, kind: str, item_id: str) -> None:
    """Unstar an executable. Idempotent: removing one that is not starred is not an error."""
    get_supabase().table(TABLE).delete()\
        .eq('team_id', team_id)\
        .eq('user_id', user_id)\
        .eq('kind', kind)\
        .eq('item_id', item_id)\
        .execute()
