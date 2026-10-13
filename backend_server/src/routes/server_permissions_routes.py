"""
Permissions Routes — Fine-grained permission management

Endpoints:
  GET  /server/permissions/matrix            — full permission matrix (admin only)
  GET  /server/users/:user_id/permissions    — effective permissions for a user
  GET  /server/roles                         — role catalog + default permissions (any signed-in user)
  PUT  /server/roles/:role                   — edit a role's defaults, preferred name, device limit
"""

import uuid

from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import (
    ADMIN_ONLY_PERMISSIONS,
    EDITABLE_ROLES,
    ROLE_RANK,
    forbid_escalation,
    in_org_scope,
    invalidate_role_defaults_cache,
    org_scope_team_ids,
    require_permission,
    role_default_permissions,
)
from backend_server.src.lib.device_scope import clean_devices
from shared.src.lib.database import role_permissions_db, roles_db, users_db
from shared.src.lib.utils.supabase_utils import get_supabase_client

server_permissions_bp = Blueprint('server_permissions', __name__)

_ALL_PERMISSIONS = [
    'dashboard:view',
    'device_control:view', 'device_control:execute', 'device_control:reboot', 'device_control:restart_streams',
    'device_control:pair',
    'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:delete', 'testcases:hide',
    'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:delete', 'campaigns:execute',
    'builder.test:view', 'builder.test:use',
    'builder.campaign:view', 'builder.campaign:use',
    'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
    'execution.monitor:view',
    'execution.build:view', 'execution.build:use',
    'reports.tests:view', 'reports.tests:share', 'reports.campaigns:view', 'reports.models:view', 'reports.dependency:view',
    'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
    'monitoring.public_ask:view',
    'interface:view', 'interface:create', 'interface:edit', 'interface:delete',
    'ai_agent:view', 'ai_agent:use',
    'ai.training:view', 'ai.training:review',
    'plugins.grafana:view', 'plugins.langfuse:view', 'plugins.postman:view',
    'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view', 'plugins.testrail:manage', 'plugins.slack:view',
    'plugins.gitlab:view', 'plugins.gitlab:manage',
    'settings.general:view', 'settings.general:edit',
    'settings.models:view', 'settings.models:edit',
    'settings.code_deploy:view', 'settings.code_deploy:use',
    'settings.cicd:view', 'settings.cicd:edit',
    'settings.branding:view', 'settings.branding:edit',
    'settings.status:view',
    'settings.logs:view',
    'system.services:restart', 'system.hosts:run_command',
    'security:view',
    'org.users:view', 'org.users:create', 'org.users:edit', 'org.users:delete',
    'org.roles:view', 'org.roles:edit',
    'org.teams:view', 'org.teams:create', 'org.teams:edit', 'org.teams:delete', 'org.teams:manage_members',
    'org.invite:send',
    # Gated by require_permission on the /server/workspaces routes.
    'org.workspaces:view', 'org.workspaces:create', 'org.workspaces:edit',
    'org.workspaces:delete', 'org.workspaces:manage_members',
    # Run management (TASK-42); reads use reports.tests:view.
    'reports.runs:edit', 'reports.defects:edit', 'reports.share:create', 'reports.manual:execute',
]


def _compute_effective(user: dict) -> dict:
    """Effective permissions of a user dict from users_db, and where each one comes from.

    effective = (role defaults ∪ individual grants − denials) ∩ team ceiling  (TASK-31)

    `sources` gives every vocabulary permission one status, for the colour legend:
      role      held, from the role's defaults
      grant     held, an individual grant beyond the role
      denied    the role or a grant would give it, an explicit denial takes it away
      capped    the role or a grant would give it, the team ceiling blocks it
      none      not held
    An admin holds everything: every permission is 'role', denials and ceilings never apply.
    """
    role = user.get('role', 'viewer')
    grants = set(user.get('permissions', []) or [])
    denied = set(user.get('denied_permissions', []) or [])
    ceiling = user.get('team_ceiling')
    # Treat empty list and None the same: migration 028 backfilled teams.permissions
    # from NULL to '[]'::jsonb, and that flows through every member's team_ceiling
    # claim. An empty grant list means "nothing configured", not "everything
    # forbidden" — converting it to None at read time matches what
    # shared/src/lib/database/users_db.py:team_cap() does for new data and keeps
    # role defaults + individual grants usable on the default team.
    ceiling_set = None if not ceiling else set(ceiling)

    if role == 'admin':
        role_perms = set(_ALL_PERMISSIONS)
        sources = {p: 'role' for p in _ALL_PERMISSIONS}
    else:
        role_perms = set(role_default_permissions(role))
        sources = {}
        for p in _ALL_PERMISSIONS:
            if p not in role_perms and p not in grants:
                sources[p] = 'none'
            elif p in denied:
                sources[p] = 'denied'
            elif ceiling_set is not None and p not in ceiling_set:
                sources[p] = 'capped'
            else:
                sources[p] = 'role' if p in role_perms else 'grant'

    return {
        'role': role,
        'role_permissions': sorted(role_perms),
        'team_ceiling': None if ceiling_set is None else sorted(ceiling_set),
        'individual_grants': sorted(grants),
        'denied_permissions': sorted(denied),
        'effective': sorted(p for p, src in sources.items() if src in ('role', 'grant')),
        'sources': sources,
    }


@server_permissions_bp.route('/server/users/<user_id>/permissions', methods=['GET'])
@require_permission('org.users:view')
@handle_route_exceptions('permissions:get_user_permissions')
def get_user_permissions(user_id: str):
    """Return effective permission breakdown for a specific user."""
    # Accepts an email as well as a UUID — provisioning callers only hold the email.
    resolved = users_db.resolve_user_id(user_id)
    user = users_db.get_user(resolved) if resolved else None
    if not user or not in_org_scope(user.get('team_ids'), org_scope_team_ids()):
        return jsonify({'success': False, 'error': 'User not found'}), 404

    result = _compute_effective(user)
    return jsonify({
        'success': True,
        'user_id': resolved,
        **result,
    })


@server_permissions_bp.route('/server/permissions/matrix', methods=['GET'])
@require_permission('org.users:view')
@handle_route_exceptions('permissions:get_matrix')
def get_permission_matrix():
    """Return permission matrix for all users (admin only)."""
    scope = org_scope_team_ids()
    all_users = [u for u in users_db.get_all_users() if in_org_scope(u.get('team_ids'), scope)]

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
            'team_ceiling': effective_info['team_ceiling'],
        })

    return jsonify({
        'success': True,
        'permissions': _ALL_PERMISSIONS,
        'users': users_with_effective,
    })


@server_permissions_bp.route('/server/roles', methods=['GET'])
@handle_route_exceptions('permissions:get_roles')
def get_roles():
    """The role catalog: every role's default permissions, preferred name, rank and device limit.

    Open to any signed-in principal: the frontend PermissionContext needs the caller's own
    role defaults to decide what to show, and every page that shows a role needs its name.
    Neither is sensitive — they are the same for everyone holding the role.

    `roles` maps role -> default permissions (admin -> the whole vocabulary). `catalog` lists
    the roles most privileged first. `admin_only_permissions` can never be a role default.
    """
    catalog = roles_db.get_role_catalog()
    if catalog is None:
        return jsonify({'success': False, 'error': 'Failed to read the role catalog'}), 500

    return jsonify({
        'success': True,
        'roles': {
            'admin': list(_ALL_PERMISSIONS),
            **{role: sorted(role_default_permissions(role)) for role in EDITABLE_ROLES},
        },
        'catalog': [
            {
                'role': role,
                'display_name': (catalog.get(role) or {}).get('display_name') or role.capitalize(),
                'rank': rank,
                'editable': role in EDITABLE_ROLES,
                'allowed_devices': (catalog.get(role) or {}).get('allowed_devices'),
            }
            for role, rank in ROLE_RANK.items()
        ],
        'admin_only_permissions': sorted(ADMIN_ONLY_PERMISSIONS),
    })



@server_permissions_bp.route('/server/roles/<role>', methods=['PUT'])
@require_permission('org.roles:edit')
@handle_route_exceptions('permissions:update_role')
def update_role(role: str):
    """Edit a role. Any of: `permissions` and `allowed_devices` (not admin), `display_name` (the
    preferred name, unique ignoring case). `allowed_devices: null` removes the device limit."""
    if role not in ROLE_RANK:
        return jsonify({'success': False, 'error': f"Unknown role '{role}'"}), 404

    data = request.get_json(silent=True) or {}
    if not any(k in data for k in ('permissions', 'display_name', 'allowed_devices')):
        return jsonify({'success': False,
                        'error': "Send at least one of 'permissions', 'display_name', 'allowed_devices'"}), 400

    devices = None
    if 'allowed_devices' in data:
        if role not in EDITABLE_ROLES:
            return jsonify({'success': False, 'error': 'Admin always sees every device'}), 400
        devices, error = clean_devices(data['allowed_devices'])
        if error:
            return jsonify({'success': False, 'error': error}), 400

    permissions = data.get('permissions')
    if permissions is not None:
        if role not in EDITABLE_ROLES:
            return jsonify({'success': False, 'error': 'Admin always holds every permission'}), 400
        if not isinstance(permissions, list) or not all(isinstance(p, str) for p in permissions):
            return jsonify({'success': False, 'error': "'permissions' must be a list of strings"}), 400

        unknown = sorted(set(permissions) - set(_ALL_PERMISSIONS))
        if unknown:
            return jsonify({'success': False, 'error': f'Unknown permissions: {unknown}'}), 400

        admin_only = sorted(set(permissions) & ADMIN_ONLY_PERMISSIONS)
        if admin_only:
            return jsonify({'success': False,
                            'error': f'Only admins hold these; no role can: {admin_only}'}), 400

        # Viewers are read-only (enforce_viewer_read_only blocks every write whatever they hold),
        # so only view permissions can be given to or taken from the role.
        if role == 'viewer':
            not_view = sorted(p for p in permissions if not p.endswith(':view'))
            if not_view:
                return jsonify({'success': False, 'error': f'Viewer can only hold view permissions: {not_view}'}), 400

        denied = forbid_escalation(set(permissions) - role_default_permissions(role), f'edit the {role} role')
        if denied:
            return denied

    display_name = data.get('display_name')
    if display_name is not None:
        display_name = str(display_name).strip()
        if not display_name:
            return jsonify({'success': False, 'error': "'display_name' cannot be empty"}), 400

    # updated_by is a profiles FK; the auto-sign and service principals have no profile.
    updated_by = getattr(request, 'user_id', None)
    try:
        uuid.UUID(str(updated_by))
    except ValueError:
        updated_by = None

    stored = None
    if permissions is not None:
        stored = role_permissions_db.update_role_permissions(role, sorted(set(permissions)), updated_by)
        if stored is None:
            return jsonify({'success': False, 'error': 'Failed to save role permissions'}), 500
        invalidate_role_defaults_cache()

    if display_name is not None:
        try:
            saved = roles_db.update_display_name(role, display_name, updated_by)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 409
        if not saved:
            return jsonify({'success': False, 'error': 'Failed to save the preferred name'}), 500

    if 'allowed_devices' in data and not roles_db.update_allowed_devices(role, devices, updated_by):
        return jsonify({'success': False, 'error': 'Failed to save the device limit'}), 500

    return jsonify({
        'success': True,
        'role': role,
        'permissions': stored if stored is not None else sorted(role_default_permissions(role)),
        'display_name': display_name,
    })
