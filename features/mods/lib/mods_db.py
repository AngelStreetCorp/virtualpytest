"""user_mod_preferences access (features/mods/db/001_user_mod_preferences.sql).

Every query filters by team_id and the caller's user_id.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

TABLE = 'user_mod_preferences'
LAYOUT_TABLE = 'user_widget_layouts'
MAX_MOD_ID_LENGTH = 100


def _client():
    client = get_supabase_client()
    if client is None:
        raise RuntimeError('Supabase client not available')
    return client


# PGRST205 / 42P01: this database has never had the mods tables (features/mods/db/*.sql
# are applied by hand, not by any deploy script). That is a deployment gap, not a
# server fault, and the app already has a supported way to cope: the browser keeps the
# choices/layout (useModPreferencesSync / useWidgetLayoutSync both treat a failed fetch
# as "stay in this browser"). So we answer with the same empty result instead of a 500
# the frontend can only log. Every other error still propagates.
_MISSING_TABLE_CODES = ('PGRST205', '42P01')


def _missing_table(err: Exception) -> bool:
    """True when `err` is PostgREST/Postgres saying one of our tables is absent."""
    code = str(getattr(err, 'code', '') or '').strip()
    if code in _MISSING_TABLE_CODES:
        return True
    message = str(err)
    if 'Could not find the table' not in message and 'does not exist' not in message:
        return False
    return any(f"'{name}'" in message for name in (TABLE, LAYOUT_TABLE))


def _read_rows(query, table: str) -> list:
    """`query.execute().data`, or [] when this database lacks `table`."""
    try:
        return (query.execute()).data or []
    except Exception as err:  # noqa: BLE001 - narrowed by _missing_table below
        if not _missing_table(err):
            raise
        print(f"[@mods:mods_db] table public.{table} is missing on this database "
              f"(apply features/mods/db/*.sql); falling back to browser storage")
        return []


def _write(query, table: str) -> None:
    """`query.execute()`, tolerating a database that lacks `table`."""
    try:
        query.execute()
    except Exception as err:  # noqa: BLE001 - narrowed by _missing_table below
        if not _missing_table(err):
            raise
        print(f"[@mods:mods_db] table public.{table} is missing on this database "
              f"(apply features/mods/db/*.sql); the change stays in this browser")


def get_choices(team_id: str, user_id: str) -> Dict[str, bool]:
    """`{mod_id: enabled}` for every mod this user switched in this team."""
    rows = _read_rows(
        _client().table(TABLE)
        .select('mod_id, enabled')
        .eq('team_id', team_id)
        .eq('user_id', user_id),
        TABLE,
    )
    return {row['mod_id']: bool(row['enabled']) for row in rows}


def set_choice(team_id: str, user_id: str, mod_id: str, enabled: bool) -> None:
    _write(
        _client().table(TABLE).upsert(
            {
                'team_id': team_id,
                'user_id': user_id,
                'mod_id': mod_id,
                'enabled': enabled,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
            on_conflict='team_id,user_id,mod_id',
        ),
        TABLE,
    )


def valid_mod_id(mod_id: Optional[str]) -> bool:
    return isinstance(mod_id, str) and 0 < len(mod_id.strip()) <= MAX_MOD_ID_LENGTH


def get_widget_layout(team_id: str, user_id: str, area: str) -> Optional[list]:
    """This user's layout of `area` in this team, or None when never saved."""
    rows = _read_rows(
        _client().table(LAYOUT_TABLE)
        .select('layout')
        .eq('team_id', team_id)
        .eq('user_id', user_id)
        .eq('area', area)
        .limit(1),
        LAYOUT_TABLE,
    )
    return rows[0]['layout'] if rows else None


def set_widget_layout(team_id: str, user_id: str, area: str, layout: list) -> None:
    _write(
        _client().table(LAYOUT_TABLE).upsert(
            {
                'team_id': team_id,
                'user_id': user_id,
                'area': area,
                'layout': layout,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            },
            on_conflict='team_id,user_id,area',
        ),
        LAYOUT_TABLE,
    )
