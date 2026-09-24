"""
Permissions Routes — Fine-grained permission management

Endpoints:
  GET  /server/permissions/matrix            — full permission matrix (admin only)
  GET  /server/users/:user_id/permissions    — effective permissions for a user
"""

from flask import Blueprint, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_admin_role
from shared.src.lib.database import users_db
from shared.src.lib.utils.supabase_utils import get_supabase_client

server_permissions_bp = Blueprint('server_permissions', __name__)

# Role defaults — mirrors auth_middleware.py ROLE_PERMISSIONS
_ROLE_PERMISSIONS: dict = {
    'admin': None,  # None = all permissions
    'tester': [
        'dashboard:view',
        'device_control:view', 'device_control:execute',
        'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:hide',
        'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:execute',
        'builder.test:view', 'builder.test:use',
        'builder.campaign:view', 'builder.campaign:use',
        'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
        'execution.monitor:view',
        'reports.tests:view', 'reports.campaigns:view',
        'reports.models:view', 'reports.dependency:view',
        'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
        'interface:view',
        'ai_agent:view', 'ai_agent:use',
        'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view',
        'settings.status:view',
    ],
    'viewer': [
        'dashboard:view',
        'testcases:view', 'campaigns:view',
        'reports.tests:view', 'reports.campaigns:view',
        'reports.models:view', 'reports.dependency:view',
        'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
        'settings.status:view',
    ],
}

_ALL_PERMISSIONS = [
    'dashboard:view',
    'device_control:view', 'device_control:execute', 'device_control:reboot', 'device_control:restart_streams',
    'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:delete', 'testcases:hide',
    'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:delete', 'campaigns:execute',
    'builder.test:view', 'builder.test:use',
    'builder.campaign:view', 'builder.campaign:use',
    'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
    'execution.monitor:view',
    'execution.build:view', 'execution.build:use',
    'reports.tests:view', 'reports.campaigns:view', 'reports.models:view', 'reports.dependency:view',
    'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
    'interface:view', 'interface:create', 'interface:edit', 'interface:delete',
    'ai_agent:view', 'ai_agent:use',
    'plugins.grafana:view', 'plugins.langfuse:view', 'plugins.postman:view',
    'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view', 'plugins.testrail:manage', 'plugins.slack:view',
    'settings.general:view', 'settings.general:edit',
    'settings.models:view', 'settings.models:edit',
    'settings.code_deploy:view', 'settings.code_deploy:use',
    'settings.cicd:view',
    'settings.branding:view', 'settings.branding:edit',
    'settings.status:view',
    'org.users:view', 'org.users:edit', 'org.users:delete',
    'org.teams:view', 'org.teams:create', 'org.teams:edit', 'org.teams:delete', 'org.teams:manage_members',
    'org.invite:send',
    # Declared and offered on the Users/Teams permission editors, but not yet a gate:
    # every /server/workspaces route is @require_admin_role. Listed here so the matrix
    # API reports the same vocabulary the frontend renders.
    'org.workspaces:view', 'org.workspaces:create', 'org.workspaces:edit',
    'org.workspaces:delete', 'org.workspaces:manage_members',
]


def _compute_effective(user: dict) -> dict:
    """Compute the full effective permission set for a user dict from users_db."""
    role = user.get('role', 'viewer')
    individual_grants = user.get('permissions', []) or []
    team_permissions = user.get('team_permissions', []) or []
    denied = set(user.get('denied_permissions', []) or [])

    if role == 'admin':
        role_perms = list(_ALL_PERMISSIONS)
    else:
        role_perms = list(_ROLE_PERMISSIONS.get(role, []))

    # Denials never apply to an admin — require_permission() returns before it reads them
    # (auth_middleware.py), and so does the frontend PermissionContext. Subtracting them here
    # made this API the only thing in the system that said an admin lacked a permission they
    # in fact hold, for any admin carrying a leftover denial from an earlier role.
    effective: set
    if role == 'admin':
        effective = set(role_perms)
    else:
        effective = {
            p for p in role_perms + list(team_permissions) + list(individual_grants)
            if p not in denied
        }

    return {
        'role': role,
        'role_permissions': role_perms,
        'team_permissions': list(team_permissions),
        'individual_grants': list(individual_grants),
        'denied_permissions': list(denied),
        'effective': sorted(effective),
    }


@server_permissions_bp.route('/server/users/<user_id>/permissions', methods=['GET'])
@require_admin_role
@handle_route_exceptions('permissions:get_user_permissions')
def get_user_permissions(user_id: str):
    """Return effective permission breakdown for a specific user."""
    # Accepts an email as well as a UUID — provisioning callers only hold the email.
    resolved = users_db.resolve_user_id(user_id)
    user = users_db.get_user(resolved) if resolved else None
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    result = _compute_effective(user)
    return jsonify({
        'success': True,
        'user_id': resolved,
        **result,
    })


@server_permissions_bp.route('/server/permissions/matrix', methods=['GET'])
@require_admin_role
@handle_route_exceptions('permissions:get_matrix')
def get_permission_matrix():
    """Return permission matrix for all users (admin only)."""
    all_users = users_db.get_all_users()

    users_with_effective = []
    for u in all_users:
        effective_info = _compute_effective(u)
        users_with_effective.append({
            'id': u['id'],
            'email': u.get('email', ''),
            'full_name': u.get('full_name', ''),
            'role': u.get('role', 'viewer'),
            'effective': effective_info['effective'],
            'denied_permissions': effective_info['denied_permissions'],
            'individual_grants': effective_info['individual_grants'],
            'team_permissions': effective_info['team_permissions'],
        })

    return jsonify({
        'success': True,
        'permissions': _ALL_PERMISSIONS,
        'users': users_with_effective,
    })
