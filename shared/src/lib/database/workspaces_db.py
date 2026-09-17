"""
Workspaces Database Operations

This module provides functions for managing workspaces in the database.
Workspaces are named scoped contexts that restrict a user's permissions,
devices, and project visibility.
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

def _make_slug(name: str) -> str:
    """Generate a URL-safe slug from a workspace name."""
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-'))

def get_all_workspaces() -> List[Dict]:
    """Retrieve all workspaces from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('workspaces').select('*').order('created_at', desc=False).execute()

        workspaces = []
        for workspace in result.data:
            count_result = supabase.table('workspace_members')\
                .select('id', count='exact')\
                .eq('workspace_id', workspace['id'])\
                .execute()
            member_count = count_result.count if count_result.count is not None else 0

            workspaces.append({
                'id': workspace['id'],
                'name': workspace['name'],
                'slug': workspace['slug'],
                'description': workspace.get('description', ''),
                'permissions': workspace.get('permissions', []),
                'denied_permissions': workspace.get('denied_permissions', []),
                'device_filter': workspace.get('device_filter', []),
                'script_filter': workspace.get('script_filter', []),
                'project_tags': workspace.get('project_tags', []),
                'hidden_pages': workspace.get('hidden_pages', []),
                'is_public': workspace.get('is_public', False),
                'member_count': member_count,
                'created_at': workspace['created_at'],
                'updated_at': workspace['updated_at'],
            })

        return workspaces
    except Exception as e:
        print(f"[@db:workspaces_db:get_all_workspaces] Error: {e}")
        return []

def get_workspace(workspace_id: str) -> Optional[Dict]:
    """Retrieve a workspace by ID from Supabase."""
    supabase = get_supabase()
    try:
        result = supabase.table('workspaces').select('*').eq('id', workspace_id).single().execute()

        if result.data:
            workspace = result.data
            count_result = supabase.table('workspace_members')\
                .select('id', count='exact')\
                .eq('workspace_id', workspace_id)\
                .execute()
            member_count = count_result.count if count_result.count is not None else 0

            return {
                'id': workspace['id'],
                'name': workspace['name'],
                'slug': workspace['slug'],
                'description': workspace.get('description', ''),
                'permissions': workspace.get('permissions', []),
                'denied_permissions': workspace.get('denied_permissions', []),
                'device_filter': workspace.get('device_filter', []),
                'script_filter': workspace.get('script_filter', []),
                'project_tags': workspace.get('project_tags', []),
                'hidden_pages': workspace.get('hidden_pages', []),
                'is_public': workspace.get('is_public', False),
                'member_count': member_count,
                'created_at': workspace['created_at'],
                'updated_at': workspace['updated_at'],
            }
        return None
    except Exception as e:
        print(f"[@db:workspaces_db:get_workspace] Error: {e}")
        return None

class DuplicateSlugError(Exception):
    """A workspace with this slug already exists (unique violation on workspaces.slug)."""

    def __init__(self, slug: str):
        self.slug = slug
        super().__init__(f"A workspace with slug '{slug}' already exists")


def _is_duplicate_slug(error: Exception) -> bool:
    """True for postgres 23505 on the workspaces_slug_key constraint.

    postgrest reports it as a dict-ish payload on the exception, so match on the code and
    the constraint name in the string form rather than on an exception type.
    """
    text = str(error)
    return '23505' in text and 'workspaces_slug_key' in text


def create_workspace(data: Dict) -> Optional[Dict]:
    """Create a new workspace.

    Raises DuplicateSlugError when the slug is taken; returns None for any other failure.
    """
    supabase = get_supabase()
    try:
        name = data['name']
        slug = data.get('slug') or _make_slug(name)

        insert_data = {
            'name': name,
            'slug': slug,
            'description': data.get('description', ''),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        for field in ('permissions', 'denied_permissions', 'device_filter', 'script_filter', 'project_tags', 'hidden_pages', 'is_public'):
            if field in data:
                insert_data[field] = data[field]

        result = supabase.table('workspaces').insert(insert_data).execute()

        if result.data and len(result.data) > 0:
            workspace = result.data[0]
            return {
                'id': workspace['id'],
                'name': workspace['name'],
                'slug': workspace['slug'],
                'description': workspace.get('description', ''),
                'permissions': workspace.get('permissions', []),
                'denied_permissions': workspace.get('denied_permissions', []),
                'device_filter': workspace.get('device_filter', []),
                'script_filter': workspace.get('script_filter', []),
                'project_tags': workspace.get('project_tags', []),
                'hidden_pages': workspace.get('hidden_pages', []),
                'is_public': workspace.get('is_public', False),
                'member_count': 0,
                'created_at': workspace['created_at'],
                'updated_at': workspace['updated_at'],
            }
        return None
    except Exception as e:
        print(f"[@db:workspaces_db:create_workspace] Error: {e}")
        # A taken slug is caller input, not a server fault. Returning None for it made the
        # route answer a blanket 500 "Failed to create workspace", which reads as an outage
        # and told the caller nothing about the one thing they could fix. Signal it apart.
        if _is_duplicate_slug(e):
            raise DuplicateSlugError(data.get('slug') or _make_slug(data.get('name', '')))
        return None

def update_workspace(workspace_id: str, data: Dict) -> Optional[Dict]:
    """Update an existing workspace."""
    supabase = get_supabase()
    try:
        update_data = {
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        for field in ('name', 'slug', 'description', 'permissions', 'denied_permissions',
                      'device_filter', 'script_filter', 'project_tags', 'hidden_pages', 'is_public'):
            if field in data:
                update_data[field] = data[field]

        result = supabase.table('workspaces').update(update_data).eq('id', workspace_id).execute()

        if result.data and len(result.data) > 0:
            workspace = result.data[0]
            count_result = supabase.table('workspace_members')\
                .select('id', count='exact')\
                .eq('workspace_id', workspace_id)\
                .execute()
            member_count = count_result.count if count_result.count is not None else 0

            return {
                'id': workspace['id'],
                'name': workspace['name'],
                'slug': workspace['slug'],
                'description': workspace.get('description', ''),
                'permissions': workspace.get('permissions', []),
                'denied_permissions': workspace.get('denied_permissions', []),
                'device_filter': workspace.get('device_filter', []),
                'script_filter': workspace.get('script_filter', []),
                'project_tags': workspace.get('project_tags', []),
                'hidden_pages': workspace.get('hidden_pages', []),
                'is_public': workspace.get('is_public', False),
                'member_count': member_count,
                'created_at': workspace['created_at'],
                'updated_at': workspace['updated_at'],
            }
        return None
    except Exception as e:
        print(f"[@db:workspaces_db:update_workspace] Error: {e}")
        return None

def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace."""
    supabase = get_supabase()
    try:
        workspace = get_workspace(workspace_id)
        if not workspace:
            print(f"[@db:workspaces_db:delete_workspace] Workspace not found: {workspace_id}")
            return False

        result = supabase.table('workspaces').delete().eq('id', workspace_id).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"[@db:workspaces_db:delete_workspace] Error: {e}")
        return False

def get_workspace_members(workspace_id: str) -> List[Dict]:
    """Get all members of a workspace (users and teams)."""
    supabase = get_supabase()
    try:
        result = supabase.table('workspace_members')\
            .select('*, profiles(*), teams(*)')\
            .eq('workspace_id', workspace_id)\
            .execute()

        members = []
        for member in result.data:
            if member.get('profiles'):
                profile = member['profiles']
                members.append({
                    'id': member['id'],
                    'type': 'user',
                    'user_id': profile['id'],
                    'full_name': profile.get('full_name', ''),
                    'email': profile.get('email', ''),
                    'role': member.get('role', 'member'),
                    'created_at': member.get('created_at'),
                })
            elif member.get('teams'):
                team = member['teams']
                members.append({
                    'id': member['id'],
                    'type': 'team',
                    'team_id': team['id'],
                    'team_name': team.get('name', ''),
                    'role': member.get('role', 'member'),
                    'created_at': member.get('created_at'),
                })

        return members
    except Exception as e:
        print(f"[@db:workspaces_db:get_workspace_members] Error: {e}")
        return []

def add_workspace_user(workspace_id: str, user_id: str, role: str = 'member') -> Optional[Dict]:
    """Add a user directly to a workspace."""
    supabase = get_supabase()
    try:
        insert_data = {
            'workspace_id': workspace_id,
            'user_id': user_id,
            'role': role,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        result = supabase.table('workspace_members').insert(insert_data).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        print(f"[@db:workspaces_db:add_workspace_user] Error: {e}")
        return None

def add_workspace_team(workspace_id: str, team_id: str, role: str = 'member') -> Optional[Dict]:
    """Add a team to a workspace."""
    supabase = get_supabase()
    try:
        insert_data = {
            'workspace_id': workspace_id,
            'team_id': team_id,
            'role': role,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        result = supabase.table('workspace_members').insert(insert_data).execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        print(f"[@db:workspaces_db:add_workspace_team] Error: {e}")
        return None

def remove_workspace_member(workspace_id: str, member_id: str) -> bool:
    """Remove a member from a workspace by workspace_members.id."""
    supabase = get_supabase()
    try:
        result = supabase.table('workspace_members')\
            .delete()\
            .eq('id', member_id)\
            .eq('workspace_id', workspace_id)\
            .execute()
        return True
    except Exception as e:
        print(f"[@db:workspaces_db:remove_workspace_member] Error: {e}")
        return False

def get_user_workspaces(user_id: str) -> List[Dict]:
    """Get all workspaces a user has access to (direct + via team membership)."""
    supabase = get_supabase()
    try:
        rpc_result = supabase.rpc('get_user_workspaces', {'p_user_id': user_id}).execute()

        if not rpc_result.data:
            return []

        seen: set = set()
        workspace_ids: List[str] = []
        for row in rpc_result.data:
            wid = row['workspace_id']
            if wid not in seen:
                seen.add(wid)
                workspace_ids.append(wid)

        workspaces = []
        for workspace_id in workspace_ids:
            workspace = get_workspace(workspace_id)
            if workspace:
                workspaces.append(workspace)

        return workspaces
    except Exception as e:
        print(f"[@db:workspaces_db:get_user_workspaces] Error: {e}")
        return []
