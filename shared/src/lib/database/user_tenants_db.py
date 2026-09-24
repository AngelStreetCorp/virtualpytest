"""
User-Tenants Database Operations — TASK-23

Manages the `user_tenants` junction table: a many-to-many mapping of users
to tenants. One user can belong to N tenants; membership grants the user
visibility into that tenant's teams (subject to the existing `team_members`
membership on top).

The super admin grants tenants to users via this module. Regular admins
(`role = 'admin'`, `is_platform_admin = false`) have no business calling it —
their UI surface does not include the Tenants tab.

Service-role only: anon / authenticated roles are revoked.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance (service-role)."""
    return get_supabase_client()


def get_user_tenants(user_id: str) -> List[Dict]:
    """List the tenants a user belongs to, with the tenant's name and slug.

    Returns rows like:
      {'user_id': ..., 'tenant_id': ..., 'role': 'member',
       'granted_by': ..., 'created_at': ..., 'tenant': {'id', 'name', 'slug', 'is_default'}}
    """
    supabase = get_supabase()
    try:
        # Supabase-Py doesn't support arbitrary joins in select(); do the join
        # client-side by fetching tenants first, then mapping each user_tenants row.
        rows = (
            supabase.table('user_tenants')
            .select('*')
            .eq('user_id', user_id)
            .execute()
        ).data or []

        if not rows:
            return []

        tenant_ids = list({r['tenant_id'] for r in rows})
        tenants = (
            supabase.table('tenants')
            .select('id, name, slug, is_default')
            .in_('id', tenant_ids)
            .execute()
        ).data or []
        by_id = {t['id']: t for t in tenants}

        return [
            {
                'user_id': r['user_id'],
                'tenant_id': r['tenant_id'],
                'role': r.get('role', 'member'),
                'granted_by': r.get('granted_by'),
                'created_at': r.get('created_at'),
                'updated_at': r.get('updated_at'),
                'tenant': by_id.get(r['tenant_id']),
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[@db:user_tenants_db:get_user_tenants] Error: {e}")
        return []


def add_user_tenant(user_id: str, tenant_id: str, role: str = 'member',
                    granted_by: Optional[str] = None) -> Optional[Dict]:
    """Grant a user membership in a tenant. Idempotent (ON CONFLICT DO NOTHING)."""
    supabase = get_supabase()
    try:
        insert = {
            'user_id': user_id,
            'tenant_id': tenant_id,
            'role': role,
            'granted_by': granted_by,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        result = (
            supabase.table('user_tenants')
            .upsert(insert, on_conflict='user_id,tenant_id')
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]
    except Exception as e:
        print(f"[@db:user_tenants_db:add_user_tenant] Error: {e}")
        return None


def remove_user_tenant(user_id: str, tenant_id: str) -> bool:
    """Revoke a user's membership in a tenant. False if no row was deleted."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table('user_tenants')
            .delete()
            .eq('user_id', user_id)
            .eq('tenant_id', tenant_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"[@db:user_tenants_db:remove_user_tenant] Error: {e}")
        return False