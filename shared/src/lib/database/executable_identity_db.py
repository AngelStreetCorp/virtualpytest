"""
Executable identity database operations.

The TCnnn prefix and display name shown for a script / testcase / virtual
script, stored per team. This replaces the hand-edited pair
test_scripts/script_identity_map.json + frontend/public/data/script_identity_map.json
(two copies with different owners — BUG-0066); the JSON files remain a read-only
fallback for one release.

Rows are keyed by (team_id, kind, script_ref) where script_ref is
normalize_script_ref() output — the same namespace as script_results.script_name.

Reads go through a short TTL cache because resolve_script_identity() runs on
every execution, on the server and again in the script child process.

See setup/db/schema/047_executable_identity.sql.
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.script_identity_utils import normalize_script_ref

VALID_KINDS = {'script', 'campaign'}

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'

_SELECT = 'id,team_id,kind,script_ref,prefix,display_name,updated_at,updated_by'

# Identity is read on every run; a few seconds of staleness is fine and saves a
# round trip per execution. Keyed by (team_id, kind) -> (fetched_at, map).
_CACHE_TTL_SECONDS = 30.0
_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Dict[str, Optional[str]]]]] = {}


def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()


def _validate_kind(kind: Optional[str]) -> str:
    normalized = (kind or 'script').strip().lower()
    if normalized not in VALID_KINDS:
        raise ValueError(f'Invalid kind: {kind}')
    return normalized


def invalidate_identity_cache(team_id: Optional[str] = None, kind: Optional[str] = None) -> None:
    """Drop cached identity maps. No args clears everything."""
    if team_id is None and kind is None:
        _cache.clear()
        return
    for key in [k for k in _cache
                if (team_id is None or k[0] == team_id) and (kind is None or k[1] == kind)]:
        _cache.pop(key, None)


def list_executable_identities(team_id: str, kind: str = 'script') -> List[Dict[str, Any]]:
    """List stored identity rows for a team, ordered by script_ref."""
    supabase = get_supabase()
    if not supabase or not team_id:
        return []

    try:
        result = (
            supabase.table('executable_identity')
            .select(_SELECT)
            .eq('team_id', team_id)
            .eq('kind', _validate_kind(kind))
            .order('script_ref')
            .execute()
        )
        items = result.data or []
        for item in items:
            item['id'] = str(item['id'])
            item['team_id'] = str(item['team_id'])
        return items
    except Exception as e:
        print(f'[@executable_identity_db] ERROR listing identities: {e}')
        return []


def get_identity_map(team_id: str, kind: str = 'script') -> Dict[str, Dict[str, Optional[str]]]:
    """Return {script_ref: {'prefix': ..., 'display_name': ...}} for a team."""
    return {
        row['script_ref']: {
            'prefix': row.get('prefix'),
            'display_name': row.get('display_name'),
        }
        for row in list_executable_identities(team_id, kind)
        if row.get('script_ref')
    }


def get_cached_identity_map(team_id: Optional[str] = None,
                            kind: str = 'script') -> Dict[str, Dict[str, Optional[str]]]:
    """get_identity_map() behind a short TTL cache (see _CACHE_TTL_SECONDS)."""
    resolved_team = team_id or DEFAULT_TEAM_ID
    normalized_kind = _validate_kind(kind)
    cache_key = (resolved_team, normalized_kind)

    cached = _cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    identity_map = get_identity_map(resolved_team, normalized_kind)
    _cache[cache_key] = (time.time(), identity_map)
    return identity_map


def get_executable_identity(team_id: str, script_ref: str,
                            kind: str = 'script') -> Optional[Dict[str, Any]]:
    """Fetch one identity row, or None."""
    supabase = get_supabase()
    normalized_ref = normalize_script_ref(script_ref)
    if not supabase or not team_id or not normalized_ref:
        return None

    try:
        result = (
            supabase.table('executable_identity')
            .select(_SELECT)
            .eq('team_id', team_id)
            .eq('kind', _validate_kind(kind))
            .eq('script_ref', normalized_ref)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f'[@executable_identity_db] ERROR fetching identity: {e}')
        return None


def upsert_executable_identity(team_id: str, script_ref: str,
                               prefix: Optional[str] = None,
                               display_name: Optional[str] = None,
                               kind: str = 'script',
                               updated_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Create or update the identity row for a script_ref.

    Clearing both fields deletes the row rather than storing an all-NULL one, so
    "no identity" has exactly one representation (a missing row) and the legacy
    JSON fallback can still apply.

    Returns the stored row, or None on failure / after a delete.
    """
    supabase = get_supabase()
    normalized_ref = normalize_script_ref(script_ref)
    if not supabase or not team_id or not normalized_ref:
        return None

    normalized_kind = _validate_kind(kind)
    clean_prefix = (prefix or '').strip() or None
    clean_display = (display_name or '').strip() or None

    if clean_prefix is None and clean_display is None:
        delete_executable_identity(team_id, normalized_ref, normalized_kind)
        return None

    payload = {
        'team_id': team_id,
        'kind': normalized_kind,
        'script_ref': normalized_ref,
        'prefix': clean_prefix,
        'display_name': clean_display,
        'updated_by': updated_by,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }

    try:
        existing = get_executable_identity(team_id, normalized_ref, normalized_kind)
        if existing:
            result = (
                supabase.table('executable_identity')
                .update({k: v for k, v in payload.items()
                         if k not in ('team_id', 'kind', 'script_ref')})
                .eq('id', existing['id'])
                .execute()
            )
        else:
            result = supabase.table('executable_identity').insert(payload).execute()

        invalidate_identity_cache(team_id, normalized_kind)
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as e:
        print(f'[@executable_identity_db] ERROR upserting identity: {e}')
        return None


def delete_executable_identity(team_id: str, script_ref: str, kind: str = 'script') -> bool:
    """Remove the identity row for a script_ref. Missing row counts as success."""
    supabase = get_supabase()
    normalized_ref = normalize_script_ref(script_ref)
    if not supabase or not team_id or not normalized_ref:
        return False

    normalized_kind = _validate_kind(kind)
    try:
        (
            supabase.table('executable_identity')
            .delete()
            .eq('team_id', team_id)
            .eq('kind', normalized_kind)
            .eq('script_ref', normalized_ref)
            .execute()
        )
        invalidate_identity_cache(team_id, normalized_kind)
        return True
    except Exception as e:
        print(f'[@executable_identity_db] ERROR deleting identity: {e}')
        return False


def find_prefix_conflict(team_id: str, prefix: str, script_ref: str,
                         kind: str = 'script') -> Optional[str]:
    """Return another script_ref already using this prefix, or None.

    Advisory only — prefixes are deliberately not unique in the schema so that
    importing an existing map can never fail half way through.
    """
    supabase = get_supabase()
    clean_prefix = (prefix or '').strip()
    if not supabase or not team_id or not clean_prefix:
        return None

    try:
        result = (
            supabase.table('executable_identity')
            .select('script_ref')
            .eq('team_id', team_id)
            .eq('kind', _validate_kind(kind))
            .eq('prefix', clean_prefix)
            .neq('script_ref', normalize_script_ref(script_ref))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0]['script_ref'] if rows else None
    except Exception as e:
        print(f'[@executable_identity_db] ERROR checking prefix conflict: {e}')
        return None
