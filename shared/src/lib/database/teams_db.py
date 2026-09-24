"""
Teams Database Operations

This module provides functions for managing teams in the database.
Teams organize users and resources in the system.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def get_all_teams() -> List[Dict]:
    """Retrieve all teams from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('teams').select('*').order('created_at', desc=False).execute()
        
        teams = []
        for team in result.data:
            # Get member count using RPC function
            count_result = supabase.rpc('get_team_member_count', {'team_uuid': team['id']}).execute()
            member_count = count_result.data if count_result.data else 0
            
            teams.append({
                'id': team['id'],
                'name': team['name'],
                'description': team.get('description', ''),
                'tenant_id': team['tenant_id'],
                'created_by': team.get('created_by'),
                'is_default': team.get('is_default', False),
                'permissions': team.get('permissions', []),
                'member_count': member_count,
                'created_at': team['created_at'],
                'updated_at': team['updated_at']
            })
        
        return teams
    except Exception as e:
        print(f"[@db:teams_db:get_all_teams] Error: {e}")
        return []

def get_team(team_id: str) -> Optional[Dict]:
    """Retrieve a team by ID from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('teams').select('*').eq('id', team_id).single().execute()
        
        if result.data:
            team = result.data
            # Get member count
            count_result = supabase.rpc('get_team_member_count', {'team_uuid': team_id}).execute()
            member_count = count_result.data if count_result.data else 0
            
            return {
                'id': team['id'],
                'name': team['name'],
                'description': team.get('description', ''),
                'tenant_id': team['tenant_id'],
                'created_by': team.get('created_by'),
                'is_default': team.get('is_default', False),
                'permissions': team.get('permissions', []),
                'member_count': member_count,
                'created_at': team['created_at'],
                'updated_at': team['updated_at']
            }
        return None
    except Exception as e:
        print(f"[@db:teams_db:get_team] Error: {e}")
        return None

def create_team(team_data: Dict, creator_id: str = None) -> Optional[Dict]:
    """Create a new team.

    The default tenant UUID (`0000…000`) is used when `tenant_id` is not
    provided — the same fallback as `_ensure_team` and the historical behavior.
    TASK-23 made `teams.tenant_id` an FK to `tenants.id`; if the caller passes a
    custom tenant_id we validate it exists first so the route can return a
    clean 400 instead of a Postgres FK violation.
    """
    supabase = get_supabase()
    try:
        tenant_id = team_data.get('tenant_id')
        if not tenant_id:
            # Legacy callers don't pass tenant_id; the default tenant is seeded
            # by migration 20260923a so the FK target exists.
            tenant_id = '00000000-0000-0000-0000-000000000000'
        else:
            # The caller named a tenant explicitly — confirm it exists. We don't
            # require the caller to be a super admin here; the route layer does.
            from shared.src.lib.database.tenants_db import get_tenant
            if not get_tenant(tenant_id):
                print(f"[@db:teams_db:create_team] tenant_id={tenant_id} does not exist")
                return None

        insert_data = {
            'name': team_data['name'],
            'description': team_data.get('description', ''),
            'tenant_id': tenant_id,
            'created_by': creator_id,
            'is_default': team_data.get('is_default', False),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        if 'permissions' in team_data:
            insert_data['permissions'] = team_data['permissions']

        result = supabase.table('teams').insert(insert_data).execute()

        if result.data and len(result.data) > 0:
            team = result.data[0]
            return {
                'id': team['id'],
                'name': team['name'],
                'description': team.get('description', ''),
                'tenant_id': team['tenant_id'],
                'created_by': team.get('created_by'),
                'is_default': team.get('is_default', False),
                'permissions': team.get('permissions', []),
                'member_count': 0,
                'created_at': team['created_at'],
                'updated_at': team['updated_at']
            }
        return None
    except Exception as e:
        print(f"[@db:teams_db:create_team] Error: {e}")
        return None

def update_team(team_id: str, team_data: Dict) -> Optional[Dict]:
    """Update an existing team."""
    supabase = get_supabase()
    try:
        update_data = {
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        if 'name' in team_data:
            update_data['name'] = team_data['name']
        if 'description' in team_data:
            update_data['description'] = team_data['description']
        if 'is_default' in team_data:
            update_data['is_default'] = team_data['is_default']
        if 'permissions' in team_data:
            update_data['permissions'] = team_data['permissions']

        result = supabase.table('teams').update(update_data).eq('id', team_id).execute()
        
        if result.data and len(result.data) > 0:
            team = result.data[0]
            # Get member count
            count_result = supabase.rpc('get_team_member_count', {'team_uuid': team_id}).execute()
            member_count = count_result.data if count_result.data else 0
            
            return {
                'id': team['id'],
                'name': team['name'],
                'description': team.get('description', ''),
                'tenant_id': team['tenant_id'],
                'created_by': team.get('created_by'),
                'is_default': team.get('is_default', False),
                'permissions': team.get('permissions', []),
                'member_count': member_count,
                'created_at': team['created_at'],
                'updated_at': team['updated_at']
            }
        return None
    except Exception as e:
        print(f"[@db:teams_db:update_team] Error: {e}")
        return None

def delete_team(team_id: str) -> bool:
    """Delete a team."""
    supabase = get_supabase()
    try:
        # Check if team exists
        team = get_team(team_id)
        if not team:
            print(f"[@db:teams_db:delete_team] Team not found: {team_id}")
            return False
        
        result = supabase.table('teams').delete().eq('id', team_id).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[@db:teams_db:delete_team] Error: {e}")
        return False

def get_team_members(team_id: str) -> List[Dict]:
    """Get all members of a team using SECURITY DEFINER RPC to bypass RLS."""
    supabase = get_supabase()
    try:
        result = supabase.rpc('get_team_members_with_profiles', {'team_uuid': team_id}).execute()

        members = []
        for member in result.data:
            user_id = member.get('user_id', '')
            full_name = member.get('full_name', '')
            email = member.get('email', '')
            members.append({
                'id': member['id'],
                'user_id': user_id,
                'full_name': full_name or email or str(user_id)[:8],
                'email': email,
                'avatar_url': member.get('avatar_url'),
                'role': member.get('user_role', 'viewer'),
                'team_role': member.get('role', 'member'),
                'created_at': member.get('created_at')
            })

        return members
    except Exception as e:
        print(f"[@db:teams_db:get_team_members] Error: {e}")
        return []

def add_team_member(team_id: str, user_id: str, role: str = 'member') -> Optional[Dict]:
    """Add a user to a team."""
    supabase = get_supabase()
    try:
        insert_data = {
            'team_id': team_id,
            'user_id': user_id,
            'role': role,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        result = supabase.table('team_members').insert(insert_data).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        print(f"[@db:teams_db:add_team_member] Error: {e}")
        return None

def remove_team_member(team_id: str, user_id: str) -> bool:
    """Remove a user from a team."""
    supabase = get_supabase()
    try:
        result = supabase.table('team_members')\
            .delete()\
            .eq('team_id', team_id)\
            .eq('user_id', user_id)\
            .execute()
        # Report what actually happened. Returning True unconditionally meant a delete that
        # removed nothing still looked like a success to the caller.
        return bool(result.data)
    except Exception as e:
        print(f"[@db:teams_db:remove_team_member] Error: {e}")
        return False



