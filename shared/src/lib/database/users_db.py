"""
Users Database Operations

This module provides functions for managing user profiles in the database.
Users represent authenticated accounts with roles and permissions.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client, get_supabase_admin

# Which platform administers an account. Everything created here is 'virtualpytest';
# an external system provisioning over /server/users sends its own name (e.g. 'dmacp').
# Must match the SQL DEFAULT on public.profiles.provider_type (schema 018).
DEFAULT_PROVIDER_TYPE = 'virtualpytest'

def get_supabase():
    """Get the Supabase client instance (anon key, RLS-bound)."""
    return get_supabase_client()

def get_all_users() -> List[Dict]:
    """Retrieve all users from Supabase using SECURITY DEFINER RPCs to bypass RLS."""
    supabase = get_supabase()
    try:
        # Fetch all profiles and team memberships via RPCs (bypass RLS)
        profiles_result = supabase.rpc('get_all_profiles').execute()
        memberships_result = supabase.rpc('get_user_team_memberships').execute()

        # Build lookup: user_id -> list of team memberships
        user_teams: Dict[str, list] = {}
        for m in memberships_result.data:
            uid = m['user_id']
            if uid not in user_teams:
                user_teams[uid] = []
            user_teams[uid].append(m)

        # Build team_id -> team_name lookup from memberships
        team_names: Dict[str, str] = {}
        for m in memberships_result.data:
            team_names[m['team_id']] = m['team_name']

        users = []
        for profile in profiles_result.data:
            uid = profile['id']
            memberships = user_teams.get(uid, [])

            # Primary team name
            primary_team_name = team_names.get(profile.get('team_id', ''))

            # Collect team permissions across all teams
            team_permissions: list = []
            for m in memberships:
                perms = m.get('team_permissions', [])
                if isinstance(perms, list):
                    team_permissions.extend(perms)
            team_permissions = list(dict.fromkeys(team_permissions))

            users.append({
                'id': uid,
                'full_name': profile.get('full_name', ''),
                'email': profile.get('email', ''),
                'provider_type': profile.get('provider_type') or DEFAULT_PROVIDER_TYPE,
                'avatar_url': profile.get('avatar_url'),
                'role': profile.get('role', 'viewer'),
                'team_id': profile.get('team_id'),
                'team': primary_team_name,
                'teams': [m['team_name'] for m in memberships],
                'permissions': profile.get('permissions', []),
                'denied_permissions': profile.get('denied_permissions', []),
                'team_permissions': team_permissions,
                'created_at': profile.get('created_at'),
                'updated_at': profile.get('updated_at')
            })

        return users
    except Exception as e:
        print(f"[@db:users_db:get_all_users] Error: {e}")
        return []

def get_user(user_id: str) -> Optional[Dict]:
    """Retrieve a user by ID from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('profiles').select('*').eq('id', user_id).single().execute()
        
        if result.data:
            profile = result.data
            
            # Get user's teams (including permissions for permission resolution)
            teams_result = supabase.table('team_members')\
                .select('team_id, teams(name, permissions)')\
                .eq('user_id', user_id)\
                .execute()

            # Get primary team name if exists
            primary_team_name = None
            if profile.get('team_id'):
                team_result = supabase.table('teams')\
                    .select('name')\
                    .eq('id', profile['team_id'])\
                    .single()\
                    .execute()
                if team_result.data:
                    primary_team_name = team_result.data.get('name')

            # Collect team permissions across all teams the user belongs to
            team_permissions: list = []
            for t in teams_result.data:
                if t.get('teams') and isinstance(t['teams'], dict):
                    team_permissions.extend(t['teams'].get('permissions', []))
            team_permissions = list(dict.fromkeys(team_permissions))

            return {
                'id': profile['id'],
                'full_name': profile.get('full_name', ''),
                'email': profile.get('email', ''),
                'provider_type': profile.get('provider_type') or DEFAULT_PROVIDER_TYPE,
                'avatar_url': profile.get('avatar_url'),
                'role': profile.get('role', 'viewer'),
                'team_id': profile.get('team_id'),
                'team': primary_team_name,
                'teams': [t['teams']['name'] for t in teams_result.data if t.get('teams')],
                'permissions': profile.get('permissions', []),
                'denied_permissions': profile.get('denied_permissions', []),
                'team_permissions': team_permissions,
                'created_at': profile.get('created_at'),
                'updated_at': profile.get('updated_at')
            }
        return None
    except Exception as e:
        print(f"[@db:users_db:get_user] Error: {e}")
        return None

def update_user(user_id: str, user_data: Dict) -> Optional[Dict]:
    """Update an existing user profile."""
    supabase = get_supabase()
    try:
        update_data = {}
        
        if 'full_name' in user_data:
            update_data['full_name'] = user_data['full_name']
        if 'avatar_url' in user_data:
            update_data['avatar_url'] = user_data['avatar_url']
        if 'role' in user_data:
            update_data['role'] = user_data['role']
        if 'team_id' in user_data:
            update_data['team_id'] = user_data['team_id']
        if 'permissions' in user_data:
            update_data['permissions'] = user_data['permissions']
        if 'denied_permissions' in user_data:
            update_data['denied_permissions'] = user_data['denied_permissions']

        if not update_data:
            return None
        
        result = supabase.table('profiles').update(update_data).eq('id', user_id).execute()
        
        if result.data and len(result.data) > 0:
            return get_user(user_id)
        return None
    except Exception as e:
        print(f"[@db:users_db:update_user] Error: {e}")
        return None

def delete_user(user_id: str) -> bool:
    """Delete a user (admin only). Deletes from auth.users which cascades to profiles."""
    try:
        # Check if user exists
        user = get_user(user_id)
        if not user:
            print(f"[@db:users_db:delete_user] User not found: {user_id}")
            return False

        # auth.admin.delete_user requires the service_role key, not the anon client.
        admin = get_supabase_admin()
        if admin is None:
            print(f"[@db:users_db:delete_user] Admin client unavailable (SUPABASE_SERVICE_ROLE_KEY not set)")
            return False

        admin.auth.admin.delete_user(user_id)
        return True
    except Exception as e:
        print(f"[@db:users_db:delete_user] Error: {e}")
        return False

def assign_user_to_team(user_id: str, team_id: str, team_role: str = 'member') -> bool:
    """Assign a user to a team."""
    supabase = get_supabase()
    try:
        # Update user's primary team
        supabase.table('profiles').update({'team_id': team_id}).eq('id', user_id).execute()
        
        # Add to team_members if not already there
        try:
            insert_data = {
                'team_id': team_id,
                'user_id': user_id,
                'role': team_role,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            supabase.table('team_members').insert(insert_data).execute()
        except Exception:
            # Ignore if already exists (UNIQUE constraint)
            pass
        
        return True
    except Exception as e:
        print(f"[@db:users_db:assign_user_to_team] Error: {e}")
        return False

def remove_user_from_team(user_id: str, team_id: str) -> bool:
    """Remove a user from a team."""
    supabase = get_supabase()
    try:
        # Remove from team_members
        supabase.table('team_members')\
            .delete()\
            .eq('team_id', team_id)\
            .eq('user_id', user_id)\
            .execute()
        
        # Clear primary team if it matches
        profile = supabase.table('profiles').select('team_id').eq('id', user_id).single().execute()
        if profile.data and profile.data.get('team_id') == team_id:
            supabase.table('profiles').update({'team_id': None}).eq('id', user_id).execute()
        
        return True
    except Exception as e:
        print(f"[@db:users_db:remove_user_from_team] Error: {e}")
        return False


def _admin_or_raise():
    """Return the service_role client or raise (provisioning needs it)."""
    admin = get_supabase_admin()
    if admin is None:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not configured (admin client unavailable)")
    return admin


def _team_name(admin, team_id: Optional[str]) -> Optional[str]:
    if not team_id:
        return None
    try:
        r = admin.table('teams').select('name').eq('id', team_id).single().execute()
        return r.data.get('name') if r.data else None
    except Exception:
        return None


def get_user_by_email(email: str) -> Optional[Dict]:
    """Resolve a user by email using the service_role client (bypasses RLS).

    Returns a minimal profile dict ({id, email, full_name, role, team_id, team})
    or None if absent. Used by the email-keyed provisioning routes (§3.4 status, upsert).
    """
    try:
        admin = _admin_or_raise()
        r = admin.table('profiles')\
            .select('id, email, full_name, role, team_id, provider_type')\
            .eq('email', email).limit(1).execute()
        if not r.data:
            return None
        p = r.data[0]
        return {
            'id': p['id'],
            'email': p.get('email', email),
            'full_name': p.get('full_name', ''),
            'role': p.get('role', 'viewer'),
            'team_id': p.get('team_id'),
            'team': _team_name(admin, p.get('team_id')),
            'provider_type': p.get('provider_type') or DEFAULT_PROVIDER_TYPE,
        }
    except Exception as e:
        print(f"[@db:users_db:get_user_by_email] Error: {e}")
        return None


def resolve_user_id(identifier: str) -> Optional[str]:
    """Resolve a user identifier — email OR UUID — to the profile id.

    Routes are keyed by `<user_id>`, but external provisioning callers hold only an
    email (it is the join key across VirtualPyTest and Grafana). This lets both forms
    work on routes whose behaviour is identical either way.

    A UUID is returned unchanged without a lookup, preserving the existing behaviour
    where the route's own DB call decides whether the user exists. An unknown email
    returns None so the caller can answer 404.

    Not for the provisioning routes themselves (POST/GET/PUT/DELETE on /server/users):
    those branch on `_is_email` because email and UUID mean different *semantics*
    there, not just a different key.
    """
    if not identifier:
        return None
    if '@' not in identifier:
        return identifier
    user = get_user_by_email(identifier)
    return user['id'] if user else None


def _is_unique_violation(e: Exception) -> bool:
    """True when a PostgREST/Supabase error is a unique-constraint violation (23505)."""
    code = getattr(e, 'code', None)
    if code == '23505':
        return True
    # supabase-py surfaces the Postgres error as a dict in the message for some paths.
    return '23505' in str(e)


def _ensure_team(admin, group: str, tenant_id: Optional[str] = None) -> str:
    """Idempotently ensure a team named `group` exists; return its id.

    When `tenant_id` is provided (TASK-23 path), the team is created in that
    tenant. When it is not (legacy call sites), the team lands in the default
    tenant (`0000…000`). The team lookup is name-scoped, not tenant-scoped,
    so the existing-team short-circuit returns the first team named `group`
    regardless of tenant — fine because provisioning callers always name a
    unique group per customer.

    Raises RuntimeError if the team cannot be resolved or created. It must NOT
    return None on failure: the caller cannot distinguish that from "no team", so
    a failure used to be reported to the client as a 200 with "team": null and the
    caller's `group` silently discarded (BUG-0077 hid behind exactly that).
    """
    tenant_id = tenant_id or '00000000-0000-0000-0000-000000000000'
    try:
        existing = admin.table('teams').select('id').eq('name', group).limit(1).execute()
        if existing.data:
            return existing.data[0]['id']
        # tenant_id is NOT NULL; FK on teams.tenant_id -> tenants.id. Default
        # tenant is seeded by migration 20260923a so the FK target exists.
        created = admin.table('teams').insert({
            'name': group,
            'tenant_id': tenant_id,
        }).execute()
    except Exception as e:
        # A concurrent provisioning call may have created the same team between the
        # SELECT and the INSERT; that is success, not failure — re-read it.
        if _is_unique_violation(e):
            again = admin.table('teams').select('id').eq('name', group).limit(1).execute()
            if again.data:
                return again.data[0]['id']
        raise RuntimeError(f"Could not ensure team '{group}': {e}") from e

    if not created.data:
        raise RuntimeError(f"Could not ensure team '{group}': insert returned no row")
    return created.data[0]['id']


def default_full_name(email: str) -> str:
    """The preferred name we fall back to: the local part of the email.

    `marie.dupont@example.com` -> `marie.dupont`. Accounts created by an admin or by
    external provisioning carry no user_metadata, so without this every one of them
    lands with a blank name and shows as an empty cell in the users list.
    """
    return (email or '').split('@', 1)[0].strip()


def _clean_provider_type(provider_type: Optional[str]) -> Optional[str]:
    """Normalise a caller-supplied provider_type. None = 'not supplied'."""
    if provider_type is None:
        return None
    cleaned = str(provider_type).strip()
    if not cleaned:
        raise ValueError("provider_type must not be blank")
    return cleaned


def upsert_user(email: str, password: Optional[str] = None, full_name: Optional[str] = None,
                group: Optional[str] = None, default_role: str = 'viewer',
                provider_type: Optional[str] = None,
                tenant: Optional[str] = None) -> Dict:
    """Create-or-update a user (external provisioning).

    - Create: auth.admin.create_user(email, password, email_confirm=True); on the
      trigger-created profile set full_name + role=default_role.
    - Update: optionally reset password; update full_name only.
      NEVER touch role / permissions on update (VirtualPyTest owns them).
    - group -> team auto-created by name (idempotent) + team_members membership.
    - tenant -> user_tenants grant (TASK-23 Q7: explicit only; no implicit grant
      of the default tenant). When `group` is given without `tenant`, the team
      lands in the default tenant — the legacy behaviour. When `tenant` is
      given, the team (whether newly created or pre-existing) is placed in the
      named tenant, and the user gets a user_tenants row there.
      Tenant can be the UUID or the slug; both resolve via tenants_db.
    - full_name defaults to the email's local part (see default_full_name).
    - provider_type records which platform administers the account; it defaults to
      'virtualpytest' on create and is only rewritten when a caller sends one, so a
      password reset from one platform never silently reassigns another's user.

    Returns {action, user_id, email, role, team, full_name, provider_type}.
    """
    admin = _admin_or_raise()
    provider_type = _clean_provider_type(provider_type)
    existing = get_user_by_email(email)

    if existing is None:
        if not password:
            raise ValueError("password is required to create a user")
        resolved_full_name = full_name if full_name is not None else default_full_name(email)
        res = admin.auth.admin.create_user({
            'email': email,
            'password': password,
            'email_confirm': True,
            # Supabase Studio's "Display name" column reads raw_user_meta_data, not our
            # profiles table — without this an admin-created account shows as "-" there
            # however good a name we store on our own side. Both keys because Studio's
            # getDisplayName() checks display_name / full_name / name in that order.
            'user_metadata': {'display_name': resolved_full_name,
                              'full_name': resolved_full_name},
        })
        user = getattr(res, 'user', None) or res
        uid = getattr(user, 'id', None) or (user.get('id') if isinstance(user, dict) else None)
        if not uid:
            raise RuntimeError(f"create_user returned no id for {email}")
        # handle_new_user() trigger created the profiles row; set our fields.
        # The trigger applies the same two defaults, but a deployment that predates
        # the migration has the old trigger, so write them explicitly rather than
        # trusting what the trigger put there.
        resolved_provider = provider_type or DEFAULT_PROVIDER_TYPE
        profile_update = {'role': default_role, 'email': email,
                          'full_name': resolved_full_name,
                          'provider_type': resolved_provider}
        written = admin.table('profiles').update(profile_update).eq('id', uid).execute()
        # handle_new_user() already put them in the default team. Read the team_id back
        # off this write rather than reporting `"team": null` at the caller, which reads
        # as "no team" when the person is in fact in the default one (same class of lie
        # as BUG-0077, which only covered the `group` path).
        created_team_id = (written.data or [{}])[0].get('team_id')
        action = 'created'
        role = default_role
    else:
        uid = existing['id']

        profile_update = {}
        if full_name is not None:
            profile_update['full_name'] = full_name
        elif not (existing.get('full_name') or '').strip():
            # Backfill only — a name the person or an admin already chose is never
            # overwritten by a call that didn't mention one.
            profile_update['full_name'] = default_full_name(email)
        if provider_type is not None:
            profile_update['provider_type'] = provider_type

        # One auth write, not two: the password and the Studio-visible display name
        # both live on auth.users.
        auth_update = {}
        if password:
            auth_update['password'] = password
        if 'full_name' in profile_update:
            auth_update['user_metadata'] = {'display_name': profile_update['full_name'],
                                            'full_name': profile_update['full_name']}
        if auth_update:
            admin.auth.admin.update_user_by_id(uid, auth_update)
        if profile_update:
            admin.table('profiles').update(profile_update).eq('id', uid).execute()

        resolved_full_name = profile_update.get('full_name') or (existing.get('full_name') or '')
        resolved_provider = provider_type or existing.get('provider_type') or DEFAULT_PROVIDER_TYPE
        action = 'updated'
        role = existing['role']  # untouched — VirtualPyTest owns role

    team_name = existing['team'] if existing else _team_name(admin, created_team_id)
    # TASK-23: resolve the caller's `tenant` (slug or UUID) into an id we can pass
    # to _ensure_team and into user_tenants. None means "use the default tenant",
    # which keeps the legacy call paths working without code changes elsewhere.
    tenant_id_for_grant: Optional[str] = None
    if tenant:
        from shared.src.lib.database.tenants_db import get_all_tenants
        # get_all_tenants returns the list with slug + id; try slug match first,
        # then exact-UUID match. Both should converge.
        all_tenants = get_all_tenants()
        match = next(
            (t for t in all_tenants
             if t.get('slug') == tenant or t.get('id') == tenant),
            None,
        )
        if not match:
            raise RuntimeError(f"Tenant '{tenant}' does not exist")
        tenant_id_for_grant = match['id']
    if group:
        # Raises on failure rather than silently dropping the caller's `group`.
        team_id = _ensure_team(admin, group, tenant_id=tenant_id_for_grant)
        admin.table('profiles').update({'team_id': team_id}).eq('id', uid).execute()
        try:
            admin.table('team_members').insert({
                'team_id': team_id,
                'user_id': uid,
                'role': 'member',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            # UNIQUE(team_id, user_id) — already a member, which is the idempotent
            # case and the only one worth ignoring. Anything else is a real failure.
            if not _is_unique_violation(e):
                raise RuntimeError(
                    f"Could not add {email} to team '{group}': {e}"
                ) from e
        team_name = group

    # TASK-23 Q7: explicit tenant grant — never implicit. Without `tenant` we do
    # nothing here; the trigger-backed user_tenants row from signup covers the
    # default-tenant case (only for new users; for existing users there is no
    # implicit grant of any tenant).
    if tenant_id_for_grant:
        try:
            admin.table('user_tenants').upsert(
                {
                    'user_id': uid,
                    'tenant_id': tenant_id_for_grant,
                    'role': 'member',
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                },
                on_conflict='user_id,tenant_id',
            ).execute()
        except Exception as e:
            raise RuntimeError(
                f"Could not grant {email} to tenant '{tenant_id_for_grant}': {e}"
            ) from e

    return {'action': action, 'user_id': uid, 'email': email, 'role': role, 'team': team_name,
            'full_name': resolved_full_name, 'provider_type': resolved_provider,
            'tenant': tenant_id_for_grant}  # TASK-23: echo back the resolved tenant
                                              # so the route can confirm the grant.


def delete_user_by_email(email: str) -> bool:
    """Delete by email (resolves to UUID then reuses delete_user). Idempotent-ish:
    returns True when the user is absent (nothing to do)."""
    existing = get_user_by_email(email)
    if existing is None:
        return True
    return delete_user(existing['id'])



