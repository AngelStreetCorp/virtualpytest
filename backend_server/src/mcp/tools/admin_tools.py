from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter


class AdminTools:
    """User and permission administration tools for org management"""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    def list_users(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List all users in the organisation with their roles and effective permissions.

        Returns email, role, effective permissions, team memberships and denied permissions for every user.

        Example: list_users()
        """
        result = self.api.get('/server/users')
        if not isinstance(result, list):
            return {"content": [{"type": "text", "text": f"❌ Failed to fetch users: {result.get('error', 'unknown error')}"}], "isError": True}

        lines = [f"👥 Users ({len(result)}):"]
        for u in result:
            lines.append(f"  • {u.get('email', '?')} — role: {u.get('role', '?')} | id: {u.get('id', '?')}")

        return {"content": [{"type": "text", "text": "\n".join(lines)}], "isError": False}

    def get_user_permissions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the full effective permission breakdown for a specific user.

        Shows role defaults, team grants, individual grants, denied permissions and final effective set.

        Args:
            params: {
                'user_id': str (REQUIRED) - Supabase user UUID
            }

        Example: get_user_permissions(user_id='ac1723d9-0d5d-40d2-99f2-b8a9d573a757')
        """
        user_id = params.get('user_id')
        if not user_id:
            return {"content": [{"type": "text", "text": "❌ user_id is required"}], "isError": True}

        result = self.api.get(f'/server/users/{user_id}/permissions')
        if not result.get('success'):
            return {"content": [{"type": "text", "text": f"❌ {result.get('error', 'Failed to fetch permissions')}"}], "isError": True}

        lines = [
            f"🔐 Permissions for user {user_id}",
            f"   Role: {result.get('role')}",
            f"   Role defaults: {len(result.get('role_permissions', []))} permissions",
            f"   Team grants: {result.get('team_permissions', [])}",
            f"   Individual grants: {result.get('individual_grants', [])}",
            f"   Denied: {result.get('denied_permissions', [])}",
            f"   Effective ({len(result.get('effective', []))}): {result.get('effective', [])}",
        ]
        return {"content": [{"type": "text", "text": "\n".join(lines)}], "isError": False}

    def get_permission_matrix(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the full org-wide permission matrix showing all users and their effective permissions.

        Useful for auditing who can do what across the organisation.

        Example: get_permission_matrix()
        """
        result = self.api.get('/server/permissions/matrix')
        if not result.get('success'):
            return {"content": [{"type": "text", "text": f"❌ {result.get('error', 'Failed to fetch matrix')}"}], "isError": True}

        users = result.get('users', [])
        lines = [f"📊 Permission Matrix ({len(users)} users):"]
        for u in users:
            denied = u.get('denied_permissions', [])
            grants = u.get('individual_grants', [])
            team = u.get('team_permissions', [])
            extras = []
            if grants:
                extras.append(f"+grants: {grants}")
            if team:
                extras.append(f"+team: {team}")
            if denied:
                extras.append(f"-denied: {denied}")
            extra_str = f" | {', '.join(extras)}" if extras else ""
            lines.append(f"  • {u.get('email', '?')} [{u.get('role')}] — {len(u.get('effective', []))} perms{extra_str}")

        return {"content": [{"type": "text", "text": "\n".join(lines)}], "isError": False}

    def update_user_role(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Change a user's role (admin / tester / viewer).

        Args:
            params: {
                'user_id': str (REQUIRED) - Supabase user UUID
                'role': str (REQUIRED) - 'admin' | 'tester' | 'viewer'
            }

        Example: update_user_role(user_id='ac1723d9-0d5d-40d2-99f2-b8a9d573a757', role='tester')
        """
        user_id = params.get('user_id')
        role = params.get('role')
        if not user_id or not role:
            return {"content": [{"type": "text", "text": "❌ user_id and role are required"}], "isError": True}
        if role not in ('admin', 'tester', 'viewer'):
            return {"content": [{"type": "text", "text": "❌ role must be 'admin', 'tester', or 'viewer'"}], "isError": True}

        result = self.api.put(f'/server/users/{user_id}', data={'role': role})
        if not result:
            return {"content": [{"type": "text", "text": "❌ Failed to update role"}], "isError": True}

        return {"content": [{"type": "text", "text": f"✅ User {user_id} role set to '{role}'"}], "isError": False}

    def grant_user_permissions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Grant individual permissions to a user (adds to existing grants).

        Permissions use resource:action format, e.g. 'execution.run:run_test', 'testcases:hide'.

        Args:
            params: {
                'user_id': str (REQUIRED) - Supabase user UUID
                'permissions': list[str] (REQUIRED) - list of permission strings to grant
            }

        Example: grant_user_permissions(user_id='7a009103-...', permissions=['execution.run:run_test', 'execution.run:run_campaign'])
        """
        user_id = params.get('user_id')
        new_perms = params.get('permissions', [])
        if not user_id or not new_perms:
            return {"content": [{"type": "text", "text": "❌ user_id and permissions are required"}], "isError": True}

        # Fetch current grants first to merge
        current = self.api.get(f'/server/users/{user_id}/permissions')
        existing = current.get('individual_grants', []) if current.get('success') else []
        merged = list(set(existing) | set(new_perms))

        result = self.api.put(f'/server/users/{user_id}', data={'permissions': merged})
        if not result:
            return {"content": [{"type": "text", "text": "❌ Failed to update permissions"}], "isError": True}

        return {"content": [{"type": "text", "text": f"✅ Granted {new_perms} to user {user_id}\n   Total individual grants: {merged}"}], "isError": False}

    def deny_user_permissions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Explicitly deny permissions for a user (highest priority — overrides role and team grants).

        Args:
            params: {
                'user_id': str (REQUIRED) - Supabase user UUID
                'permissions': list[str] (REQUIRED) - permission strings to deny
            }

        Example: deny_user_permissions(user_id='ac1723d9-...', permissions=['testcases:delete'])
        """
        user_id = params.get('user_id')
        new_denials = params.get('permissions', [])
        if not user_id or not new_denials:
            return {"content": [{"type": "text", "text": "❌ user_id and permissions are required"}], "isError": True}

        current = self.api.get(f'/server/users/{user_id}/permissions')
        existing_denied = current.get('denied_permissions', []) if current.get('success') else []
        merged = list(set(existing_denied) | set(new_denials))

        result = self.api.put(f'/server/users/{user_id}', data={'denied_permissions': merged})
        if not result:
            return {"content": [{"type": "text", "text": "❌ Failed to update denied permissions"}], "isError": True}

        return {"content": [{"type": "text", "text": f"✅ Denied {new_denials} for user {user_id}\n   Total denied: {merged}"}], "isError": False}

    def set_team_permissions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set the permissions granted to all members of a team.

        All members inherit these permissions on top of their role defaults.

        Args:
            params: {
                'team_id': str (REQUIRED) - team UUID
                'permissions': list[str] (REQUIRED) - full list of permission strings for the team
            }

        Example: set_team_permissions(team_id='uuid-...', permissions=['execution.run:run_test', 'execution.run:run_campaign'])
        """
        team_id = params.get('team_id')
        permissions = params.get('permissions', [])
        if not team_id:
            return {"content": [{"type": "text", "text": "❌ team_id is required"}], "isError": True}

        result = self.api.put(f'/server/teams/{team_id}', data={'permissions': permissions})
        if not result:
            return {"content": [{"type": "text", "text": "❌ Failed to update team permissions"}], "isError": True}

        return {"content": [{"type": "text", "text": f"✅ Team {team_id} permissions set to: {permissions}"}], "isError": False}
