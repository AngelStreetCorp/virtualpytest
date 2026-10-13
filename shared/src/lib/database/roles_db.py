"""
Roles Database Operations

The role catalog (TASK-31): `roles` holds, for each fixed system role, its preferred name — shown
everywhere in the app and accepted from an external platform ("SuperAdmin" -> admin) — and its
device ceiling. Preferred names are unique ignoring case. Default permissions stay in
`role_permissions` (role_permissions_db).

Global, not team-scoped — same shape as role_permissions. Service-role only; the browser reads
it through GET /server/roles.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance (service-role)."""
    return get_supabase_client()


def get_role_catalog() -> Optional[Dict[str, Dict]]:
    """role -> {'display_name', 'allowed_devices' (None = no limit)}.

    None when the table cannot be read, so the caller can answer 500 rather than show a
    catalog with every name missing.
    """
    supabase = get_supabase()
    try:
        roles = supabase.table('roles').select('role, display_name, allowed_devices').execute()
    except Exception as e:
        print(f"[@db:roles_db:get_role_catalog] Error: {e}")
        return None
    return {row['role']: {'display_name': row['display_name'],
                          'allowed_devices': row.get('allowed_devices')} for row in roles.data}


def update_display_name(role: str, display_name: str, updated_by: Optional[str]) -> bool:
    """Set the role's preferred name. Raises ValueError when another role already has it."""
    supabase = get_supabase()
    try:
        result = (supabase.table('roles')
                  .update({'display_name': display_name, 'updated_by': updated_by,
                           'updated_at': datetime.now(timezone.utc).isoformat()})
                  .eq('role', role)
                  .execute())
        return bool(result.data)
    except Exception as e:
        if '23505' in str(e) or 'duplicate key' in str(e).lower():
            raise ValueError(f"'{display_name}' is already the name of another role") from e
        print(f"[@db:roles_db:update_display_name] Error: {e}")
        return False


def update_allowed_devices(role: str, devices: Optional[List[str]], updated_by: Optional[str]) -> bool:
    """Set the role's device ceiling (None = no limit)."""
    supabase = get_supabase()
    try:
        result = (supabase.table('roles')
                  .update({'allowed_devices': devices, 'updated_by': updated_by,
                           'updated_at': datetime.now(timezone.utc).isoformat()})
                  .eq('role', role)
                  .execute())
        return bool(result.data)
    except Exception as e:
        print(f"[@db:roles_db:update_allowed_devices] Error: {e}")
        return False


def role_devices(role: str) -> Optional[List[str]]:
    """The role's device ceiling, None for no limit (or when it cannot be read)."""
    catalog = get_role_catalog() or {}
    return (catalog.get(role) or {}).get('allowed_devices')


def resolve_name(name: str) -> Optional[str]:
    """The role meant by `name`: its preferred name or its id, ignoring case. None if neither."""
    wanted = (name or '').strip().lower()
    if not wanted:
        return None
    for role, info in (get_role_catalog() or {}).items():
        if wanted in (role.lower(), (info.get('display_name') or '').strip().lower()):
            return role
    return None


def role_names() -> List[str]:
    """Every accepted role name — preferred names and ids — for error messages."""
    catalog = get_role_catalog() or {}
    names = [str(info["display_name"]) for info in catalog.values() if info.get("display_name")]
    return sorted(set(names) | set(catalog), key=lambda n: n.lower())
