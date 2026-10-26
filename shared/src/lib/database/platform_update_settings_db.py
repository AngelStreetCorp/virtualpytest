"""
Platform update settings storage (TASK-128 G9).

One row per (server_name, key). The exception to "every query filters by team_id": this table configures how THIS server
updates its machines, so it is per server, not per team (like applied_migrations, the schema belongs to the install).
Every query filters by server_name instead. Service role only (RLS on, no grant to anon/authenticated).
See setup/db/schema/072_platform_update_settings.sql.

``TableMissing`` is raised when the migration is not applied yet: the caller falls back to its file store.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'platform_update_settings'


class TableMissing(Exception):
    """The table does not exist (migration 20261018g not applied) or the database client is not configured."""


def get_supabase():
    return get_supabase_client()


def _client():
    client = get_supabase()
    if client is None:
        raise TableMissing('no database client')
    return client


def _is_missing(exc: Exception) -> bool:
    text = f'{getattr(exc, "code", "")} {exc}'.lower()
    return 'pgrst205' in text or '42p01' in text or 'could not find the table' in text or 'does not exist' in text


def load(server_name: str) -> Dict[str, str]:
    """All stored values of this server, ``{key: value}``. Raises ``TableMissing`` when the table is not there."""
    try:
        result = _client().table(TABLE).select('key,value').eq('server_name', server_name).execute()
    except TableMissing:
        raise
    except Exception as exc:
        if _is_missing(exc):
            raise TableMissing(str(exc)) from exc
        raise
    return {row['key']: row['value'] for row in (result.data or []) if row.get('value')}


def save(server_name: str, values: Dict[str, str], secret_keys, updated_by: Optional[str] = None) -> None:
    """Upsert ``values``; an empty value deletes the key."""
    client = _client()
    now = datetime.now(timezone.utc).isoformat()
    rows = [{'server_name': server_name, 'key': k, 'value': v, 'is_secret': k in secret_keys,
             'updated_by': updated_by, 'updated_at': now} for k, v in values.items() if v]
    try:
        if rows:
            client.table(TABLE).upsert(rows, on_conflict='server_name,key').execute()
        for key in [k for k, v in values.items() if not v]:
            client.table(TABLE).delete().eq('server_name', server_name).eq('key', key).execute()
    except Exception as exc:
        if _is_missing(exc):
            raise TableMissing(str(exc)) from exc
        raise
