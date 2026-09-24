"""
Teams Management Routes
Handles CRUD operations for teams
"""
from flask import Blueprint, request, jsonify
from typing import Optional
import logging

from shared.src.lib.database import teams_db, tenants_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import (
    require_admin_role, _caller_is_platform_admin,
)

logger = logging.getLogger(__name__)

server_teams_bp = Blueprint('server_teams', __name__, url_prefix='/server/teams')


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
@require_admin_role
@handle_route_exceptions('server_teams:get_teams')
def get_teams():
    """
    Get all teams
    Admin: sees all teams
    Regular user: sees only their teams

    TASK-23: response is enriched with `tenant: {id, name, slug}` for platform
    admins only. Non-super-admin callers see the same fields as before TASK-23.
    """
    teams = teams_db.get_all_teams()
    if _caller_is_platform_admin():
        teams = [_enrich_team_with_tenant(t) for t in teams]
    return jsonify(teams), 200


@server_teams_bp.route('/<team_id>', methods=['GET'])
@require_admin_role
@handle_route_exceptions('server_teams:get_team')
def get_team(team_id: str):
    """Get a specific team by ID. Same tenant enrichment as get_teams."""
    team = teams_db.get_team(team_id)
    if not team:
        return jsonify({"error": "Team not found"}), 404
    team = _enrich_team_with_tenant(team)
    return jsonify(team), 200


@server_teams_bp.route('', methods=['POST'])
@require_admin_role
@handle_route_exceptions('server_teams:create_team')
def create_team():
    """Create a new team (admin only)"""
    data = request.get_json() or {}
    if not data.get('name'):
        return jsonify({"error": "Team name is required"}), 400
    team = teams_db.create_team(data)
    if not team:
        return jsonify({"error": "Failed to create team"}), 500
    logger.info(f"Team created: {team['id']}")
    return jsonify(team), 201


@server_teams_bp.route('/<team_id>', methods=['PUT'])
@require_admin_role
@handle_route_exceptions('server_teams:update_team')
def update_team(team_id: str):
    """Update a team (admin only)"""
    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    team = teams_db.update_team(team_id, data)
    if not team:
        return jsonify({"error": "Team not found"}), 404
    logger.info(f"Team updated: {team_id}")
    return jsonify(team), 200


@server_teams_bp.route('/<team_id>', methods=['DELETE'])
@require_admin_role
@handle_route_exceptions('server_teams:delete_team')
def delete_team(team_id: str):
    """Delete a team (admin only)"""
    success = teams_db.delete_team(team_id)
    if not success:
        return jsonify({"error": "Team not found"}), 404
    logger.info(f"Team deleted: {team_id}")
    return jsonify({"message": "Team deleted successfully"}), 200


@server_teams_bp.route('/<team_id>/members', methods=['GET'])
@require_admin_role
@handle_route_exceptions('server_teams:get_team_members')
def get_team_members(team_id: str):
    """Get all members of a team"""
    members = teams_db.get_team_members(team_id)
    return jsonify(members), 200


@server_teams_bp.route('/<team_id>/members', methods=['POST'])
@require_admin_role
@handle_route_exceptions('server_teams:add_team_member')
def add_team_member(team_id: str):
    """Add a user to a team (admin only)"""
    data = request.get_json() or {}
    if not data.get('user_id'):
        return jsonify({"error": "user_id is required"}), 400
    member = teams_db.add_team_member(team_id, data['user_id'], data.get('role', 'member'))
    if not member:
        return jsonify({"error": "Failed to add team member"}), 500
    logger.info(f"User {data['user_id']} added to team {team_id}")
    return jsonify(member), 201


@server_teams_bp.route('/<team_id>/members/<user_id>', methods=['DELETE'])
@require_admin_role
@handle_route_exceptions('server_teams:remove_team_member')
def remove_team_member(team_id: str, user_id: str):
    """Remove a user from a team (admin only)"""
    success = teams_db.remove_team_member(team_id, user_id)
    if not success:
        return jsonify({"error": "Failed to remove team member"}), 500
    logger.info(f"User {user_id} removed from team {team_id}")
    return jsonify({"message": "Team member removed successfully"}), 200

