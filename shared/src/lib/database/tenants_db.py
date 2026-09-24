"""
Tenants Database Operations — TASK-23

Manages the `tenants` table: first-class multi-tenant entities created by the
platform super admin. Each tenant owns N teams (FK `teams.tenant_id`); each
user belongs to N tenants via the `user_tenants` junction.

The built-in **default tenant** has the well-known UUID
`00000000-0000-0000-0000-000000000000` (seeded by migration
`20260923a_tenants_table.sql`). Every other tenant gets a random UUID at
creation.

Service-role only: anonymous and authenticated roles are revoked (the
post-TASK-10 lockdown pattern). The Flask backend uses the service-role key
to call these functions; tenants are never exposed to the browser directly.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


def get_supabase():
    """Get the Supabase client instance (service-role for tenant writes)."""
    return get_supabase_client()


def get_all_tenants() -> List[Dict]:
    """List all tenants, oldest first, with team and user counts.

    Counts are computed by the database so we don't double-supabase from
    Python — one RPC-style call per object is fine because both tables are
    RLS-isolated to service_role and the dataset is small (handful of tenants).
    """
    supabase = get_supabase()
    try:
        result = (
            supabase.table('tenants')
            .select('*')
            .order('created_at', desc=False)
            .execute()
        )

        tenants = []
        for tenant in result.data:
            # Team count
            teams = (
                supabase.table('teams')
                .select('id', count='exact')
                .eq('tenant_id', tenant['id'])
                .execute()
            )
            team_count = teams.count if teams.count is not None else 0
            # User count via the junction
            users = (
                supabase.table('user_tenants')
                .select('user_id', count='exact')
                .eq('tenant_id', tenant['id'])
                .execute()
            )
            user_count = users.count if users.count is not None else 0

            tenants.append({
                'id': tenant['id'],
                'name': tenant['name'],
                'slug': tenant['slug'],
                'description': tenant.get('description', ''),
                'is_default': tenant.get('is_default', False),
                'created_by': tenant.get('created_by'),
                'team_count': team_count,
                'user_count': user_count,
                'footer_logo_url': tenant.get('footer_logo_url'),
                'footer_logo_alt': tenant.get('footer_logo_alt'),
                'footer_text_color': tenant.get('footer_text_color'),
                'created_at': tenant['created_at'],
                'updated_at': tenant['updated_at'],
            })
        return tenants
    except Exception as e:
        print(f"[@db:tenants_db:get_all_tenants] Error: {e}")
        return []


def get_tenant(tenant_id: str) -> Optional[Dict]:
    """Fetch a single tenant by id with team + user counts. None if not found."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table('tenants')
            .select('*')
            .eq('id', tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            return None
        tenant = result.data

        teams = (
            supabase.table('teams')
            .select('id', count='exact')
            .eq('tenant_id', tenant_id)
            .execute()
        )
        users = (
            supabase.table('user_tenants')
            .select('user_id', count='exact')
            .eq('tenant_id', tenant_id)
            .execute()
        )

        return {
            'id': tenant['id'],
            'name': tenant['name'],
            'slug': tenant['slug'],
            'description': tenant.get('description', ''),
            'is_default': tenant.get('is_default', False),
            'created_by': tenant.get('created_by'),
            'team_count': teams.count or 0,
            'user_count': users.count or 0,
            'footer_logo_url': tenant.get('footer_logo_url'),
            'footer_logo_alt': tenant.get('footer_logo_alt'),
            'footer_text_color': tenant.get('footer_text_color'),
            'created_at': tenant['created_at'],
            'updated_at': tenant['updated_at'],
        }
    except Exception as e:
        print(f"[@db:tenants_db:get_tenant] Error: {e}")
        return None


def get_tenant_branding(tenant_id: str) -> Dict:
    """Return just the per-tenant branding overrides for a tenant.

    The result is always safe to expose to non-super-admin callers (it carries
    no admin-only or identifying info beyond what the tenant's own users
    already see in the footer). Empty dict if the tenant has no overrides.
    """
    supabase = get_supabase()
    try:
        result = (
            supabase.table('tenants')
            .select('footer_logo_url, footer_logo_alt, footer_text_color')
            .eq('id', tenant_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return {}
        return {
            'footer_logo_url':   rows[0].get('footer_logo_url') or None,
            'footer_logo_alt':   rows[0].get('footer_logo_alt') or None,
            'footer_text_color': rows[0].get('footer_text_color') or None,
        }
    except Exception as e:
        print(f"[@db:tenants_db:get_tenant_branding] Error: {e}")
        return {}


def get_default_tenant() -> Optional[Dict]:
    """Return the single tenant marked is_default=true (None on data corruption)."""
    supabase = get_supabase()
    try:
        result = (
            supabase.table('tenants')
            .select('*')
            .eq('is_default', True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]
    except Exception as e:
        print(f"[@db:tenants_db:get_default_tenant] Error: {e}")
        return None


def create_tenant(name: str, slug: str, description: str = '',
                  created_by: Optional[str] = None,
                  footer_logo_url: Optional[str] = None,
                  footer_logo_alt: Optional[str] = None,
                  footer_text_color: Optional[str] = None) -> Optional[Dict]:
    """Create a new tenant.

    The new tenant gets a random UUID from gen_random_uuid(). `slug` must be
    unique and match ^[a-z0-9][a-z0-9-]{0,62}$ (enforced by the SQL CHECK).
    Returns the created row, or None on failure.
    """
    supabase = get_supabase()
    try:
        insert = {
            'name': name,
            'slug': slug,
            'description': description,
            'is_default': False,
            'created_by': created_by,
            'footer_logo_url': footer_logo_url or None,
            'footer_logo_alt': footer_logo_alt or None,
            'footer_text_color': footer_text_color or None,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        result = supabase.table('tenants').insert(insert).execute()
        if not result.data:
            return None
        return result.data[0]
    except Exception as e:
        print(f"[@db:tenants_db:create_tenant] Error: {e}")
        return None


def update_tenant(tenant_id: str, name: Optional[str] = None,
                  description: Optional[str] = None,
                  slug: Optional[str] = None,
                  footer_logo_url: Optional[str] = None,
                  footer_logo_alt: Optional[str] = None,
                  footer_text_color: Optional[str] = None) -> Optional[Dict]:
    """Update mutable fields of a tenant.

    `slug` is mutable in v1; tenant IDs are stable identifiers for the FK chain
    but a rename of the slug is rare. Footer branding fields are also mutable.
    An empty string for any of the footer fields clears that field (sets NULL).
    Returns the updated row, or None.
    """
    supabase = get_supabase()
    try:
        update = {'updated_at': datetime.now(timezone.utc).isoformat()}
        if name is not None:
            update['name'] = name
        if description is not None:
            update['description'] = description
        if slug is not None:
            update['slug'] = slug
        if footer_logo_url is not None:
            update['footer_logo_url'] = footer_logo_url.strip() or None
        if footer_logo_alt is not None:
            update['footer_logo_alt'] = footer_logo_alt.strip() or None
        if footer_text_color is not None:
            update['footer_text_color'] = footer_text_color.strip() or None

        result = (
            supabase.table('tenants')
            .update(update)
            .eq('id', tenant_id)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]
    except Exception as e:
        print(f"[@db:tenants_db:update_tenant] Error: {e}")
        return None


def delete_tenant(tenant_id: str) -> bool:
    """Delete a tenant.

    Refuses (returns False) if any team still references it — the FK has
    ON DELETE RESTRICT so the database would error anyway, but checking
    first lets the route return a clean 409 with the team list.
    The default tenant is undeletable in policy (the caller should refuse
    before reaching here).
    """
    supabase = get_supabase()
    try:
        teams = (
            supabase.table('teams')
            .select('id', count='exact')
            .eq('tenant_id', tenant_id)
            .execute()
        )
        if teams.count and teams.count > 0:
            print(f"[@db:tenants_db:delete_tenant] refused: {teams.count} teams still reference tenant {tenant_id}")
            return False

        result = (
            supabase.table('tenants')
            .delete()
            .eq('id', tenant_id)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        print(f"[@db:tenants_db:delete_tenant] Error: {e}")
        return False