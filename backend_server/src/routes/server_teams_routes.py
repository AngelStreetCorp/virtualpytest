"""
Teams Management Routes
Handles CRUD operations for teams
"""
from flask import Blueprint, request, jsonify
from typing import Optional
import logging

from shared.src.lib.database import teams_db, tenants_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.device_scope import clean_devices
from backend_server.src.lib.auth_middleware import (
    caller_is_admin,
    forbid_escalation,
    forbid_role_assignment,
    org_scope_team_ids,
    require_permission,
    _caller_is_platform_admin,
)

logger = logging.getLogger(__name__)

server_teams_bp = Blueprint('server_teams', __name__, url_prefix='/server/teams')


def _check_limits(data: dict, current: Optional[dict]):
    """Validate a team's ceilings in `data` (normalised in place); the error response or None.

    `permissions` is the team's permission CEILING (TASK-31): null = no limit, a list = members
    hold nothing outside it. `allowed_devices` is its device ceiling, same convention. A non-admin
    may not lift a limit or widen it past what they hold themselves.
    """
    if 'permissions' in data:
        perms = data['permissions']
        if perms is not None and (not isinstance(perms, list) or not all(isinstance(p, str) for p in perms)):
            return jsonify({"error": "'permissions' must be a list of permissions, or null for no limit"}), 400
        if perms is None and not caller_is_admin():
            return jsonify({"error": "Forbidden", "message": "Only an admin can remove a team's limit"}), 403
        before = None if current is None else current.get('permissions')
        added = set(perms or []) - (set(before) if before is not None else set())
        denied = forbid_escalation(added, 'widen this team limit')
        if denied:
            return denied
    if 'allowed_devices' in data:
        devices, error = clean_devices(data['allowed_devices'])
        if error:
            return jsonify({"error": error}), 400
        data['allowed_devices'] = devices
    return None


def _team_in_scope(team_id: str) -> bool:
    """May the caller see and manage this team? Admins: any. Managers: their own (TASK-31)."""
    scope = org_scope_team_ids()
    return scope is None or str(team_id) in scope


def _enrich_team_with_tenant(team: Optional[dict]) -> Optional[dict]:
    """TASK-23: when the caller is a platform admin, attach the tenant object
    `{id, name, slug, is_default}` to the team dict. Non-super-admin callers
    see the same shape as before TASK-23 — just `tenant_id` (the UUID)."""
    if team is None:
        return None
    if not _caller_is_platform_admin():
        return team
    tenant = tenants_db.get_tenant(team.get('tenant_id', ''))
    if tenant:
        team = dict(team)
        team['tenant'] = {
            'id': tenant['id'],
            'name': tenant['name'],
            'slug': tenant['slug'],
            'is_default': tenant.get('is_default', False),
        }
    return team


@server_teams_bp.route('', methods=['GET'])
@require_permission('org.teams:view')
@handle_route_exceptions('server_teams:get_teams')
def get_teams():
    """
    Get all teams
    Admin: sees all teams
    Anyone else: only their own teams (the default team only when it is their only one)

    TASK-23: response is enriched with `tenant: {id, name, slug}` for platform
    admins only. Non-super-admin callers see the same fields as before TASK-23.
    """
    teams = [t for t in teams_db.get_all_teams() if _team_in_scope(t['id'])]
    if _caller_is_platform_admin():
        teams = [_enrich_team_with_tenant(t) for t in teams]
    return jsonify(teams), 200


@server_teams_bp.route('/<team_id>', methods=['GET'])
@require_permission('org.teams:view')
@handle_route_exceptions('server_teams:get_team')
def get_team(team_id: str):
    """Get a specific team by ID. Same tenant enrichment as get_teams."""
    team = teams_db.get_team(team_id)
    if not team or not _team_in_scope(team_id):
        return jsonify({"error": "Team not found"}), 404
    team = _enrich_team_with_tenant(team)
    return jsonify(team), 200


@server_teams_bp.route('', methods=['POST'])
@require_permission('org.teams:create')
@handle_route_exceptions('server_teams:create_team')
def create_team():
    """Create a new team (admin only)"""
    data = request.get_json() or {}
    if not data.get('name'):
        return jsonify({"error": "Team name is required"}), 400
    blocked = _check_limits(data, current=None)
    if blocked:
        return blocked
    team = teams_db.create_team(data)
    if not team:
        return jsonify({"error": "Failed to create team"}), 500
    logger.info(f"Team created: {team['id']}")
    return jsonify(team), 201


@server_teams_bp.route('/<team_id>', methods=['PUT'])
@require_permission('org.teams:edit')
@handle_route_exceptions('server_teams:update_team')
def update_team(team_id: str):
    """Update a team (admin only)"""
    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    if 'permissions' in data or 'allowed_devices' in data:
        current = teams_db.get_team(team_id)
        if not current:
            return jsonify({"error": "Team not found"}), 404
        blocked = _check_limits(data, current)
        if blocked:
            return blocked
    team = teams_db.update_team(team_id, data)
    if not team:
        return jsonify({"error": "Team not found"}), 404
    logger.info(f"Team updated: {team_id}")
    return jsonify(team), 200


@server_teams_bp.route('/<team_id>', methods=['DELETE'])
@require_permission('org.teams:delete')
@handle_route_exceptions('server_teams:delete_team')
def delete_team(team_id: str):
    """Delete a team (admin only)"""
    success = teams_db.delete_team(team_id)
    if not success:
        return jsonify({"error": "Team not found"}), 404
    logger.info(f"Team deleted: {team_id}")
    return jsonify({"message": "Team deleted successfully"}), 200


@server_teams_bp.route('/<team_id>/members', methods=['GET'])
@require_permission('org.teams:view')
@handle_route_exceptions('server_teams:get_team_members')
def get_team_members(team_id: str):
    """Get all members of a team"""
    if not _team_in_scope(team_id):
        return jsonify({"error": "Team not found"}), 404
    members = teams_db.get_team_members(team_id)
    return jsonify(members), 200


@server_teams_bp.route('/<team_id>/members', methods=['POST'])
@require_permission('org.teams:manage_members')
@handle_route_exceptions('server_teams:add_team_member')
def add_team_member(team_id: str):
    """Add a user to a team (admin only)"""
    data = request.get_json() or {}
    if not data.get('user_id'):
        return jsonify({"error": "user_id is required"}), 400
    # A team is a ceiling (TASK-31): joining one never gives a permission.
    team = teams_db.get_team(team_id)
    if not team or not _team_in_scope(team_id):
        return jsonify({"error": "Team not found"}), 404
    # Adding someone puts them in the caller's scope; a manager may not pull in an admin or peer.
    from shared.src.lib.database import users_db
    target = users_db.get_user(data['user_id'])
    denied = forbid_role_assignment(target.get('role'), None) if target else None
    if denied:
        return denied
    member = teams_db.add_team_member(team_id, data['user_id'], data.get('role', 'member'))
    if not member:
        return jsonify({"error": "Failed to add team member"}), 500
    logger.info(f"User {data['user_id']} added to team {team_id}")
    return jsonify(member), 201


@server_teams_bp.route('/<team_id>/members/<user_id>', methods=['DELETE'])
@require_permission('org.teams:manage_members')
@handle_route_exceptions('server_teams:remove_team_member')
def remove_team_member(team_id: str, user_id: str):
    """Remove a user from a team (admin only)"""
    if not _team_in_scope(team_id):
        return jsonify({"error": "Team not found"}), 404
    from shared.src.lib.database import users_db
    target = users_db.get_user(user_id)
    denied = forbid_role_assignment(target.get('role'), None) if target else None
    if denied:
        return denied
    success = teams_db.remove_team_member(team_id, user_id)
    if not success:
        return jsonify({"error": "Failed to remove team member"}), 500
    logger.info(f"User {user_id} removed from team {team_id}")
    return jsonify({"message": "Team member removed successfully"}), 200

