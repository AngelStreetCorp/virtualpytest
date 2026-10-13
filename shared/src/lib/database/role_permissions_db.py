"""
Role Permissions Database Operations

Manages the `role_permissions` table: the default permission set of each editable
system role (`tester`, `viewer`). `admin` has no row — it holds every permission.

Global, not team-scoped: `profiles.role` is platform-wide, so there is no team_id to
filter by (same shape as `tenants`). Service-role only; the browser reads it through
GET /server/roles.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance (service-role)."""
    return get_supabase_client()


def get_role_permissions() -> Optional[Dict[str, List[str]]]:
    """All editable roles -> their default permissions.

    Returns None when the table cannot be read, so callers can tell "no rows" from
    "database unavailable" and keep their last good copy.
    """
    supabase = get_supabase()
    try:
        result = supabase.table('role_permissions').select('role, permissions').execute()
        return {row['role']: list(row.get('permissions') or []) for row in result.data}
    except Exception as e:
        print(f"[@db:role_permissions_db:get_role_permissions] Error: {e}")
        return None


def update_role_permissions(role: str, permissions: List[str], updated_by: Optional[str]) -> Optional[List[str]]:
    """Replace a role's default permissions. Returns the stored list, or None on failure."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table('role_permissions')
            .update({
                'permissions': permissions,
                'updated_by': updated_by,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            })
            .eq('role', role)
            .execute()
        )
        if not result.data:
            return None
        return list(result.data[0].get('permissions') or [])
    except Exception as e:
        print(f"[@db:role_permissions_db:update_role_permissions] Error: {e}")
        return None
