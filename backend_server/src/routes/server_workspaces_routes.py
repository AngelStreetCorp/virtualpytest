"""
Workspaces Management Routes
Handles CRUD operations for workspaces
"""
from flask import Blueprint, request, jsonify
from typing import Optional
import logging

from shared.src.lib.database import workspaces_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import (
    principal_holds_permission,
    require_permission,
)

logger = logging.getLogger(__name__)

server_workspaces_bp = Blueprint('server_workspaces', __name__, url_prefix='/server/workspaces')


# ---------------------------------------------------------------------------
# device_filter label resolution
#
# `device_filter` stores stable `host_name:device_id` keys ("host3:device1")
# because device_id is the positional slot the host registers under and never
# changes. That is unreadable on its own, so every response that carries a
# workspace also carries a read-only `device_filter_names` map resolved from the
# live host registry. Keys whose host is not registered on this server (offline,
# or owned by another backend_server) are simply absent from the map.
# ---------------------------------------------------------------------------
def _build_device_name_map() -> dict:
    """`host_name:device_id` -> device_name, from the in-memory host registry."""
    try:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        name_map = {}
        for host_info in get_host_manager().get_all_hosts().values():
            host_name = host_info.get('host_name')
            if not host_name:
                continue
            for device in host_info.get('devices') or []:
                device_id = device.get('device_id')
                device_name = device.get('device_name')
                if device_id and device_name:
                    name_map[f"{host_name}:{device_id}"] = device_name
        return name_map
    except Exception as e:
        logger.warning(f"Could not build device name map: {e}")
        return {}


def _with_device_names(workspace_or_list):
    """Attach `device_filter_names` to a workspace dict or a list of them."""
    workspaces = workspace_or_list if isinstance(workspace_or_list, list) else [workspace_or_list]
    if not any(ws.get('device_filter') for ws in workspaces if isinstance(ws, dict)):
        return workspace_or_list
    name_map = _build_device_name_map()
    for ws in workspaces:
        if not isinstance(ws, dict):
            continue
        ws['device_filter_names'] = {
            key: name_map[key] for key in (ws.get('device_filter') or []) if key in name_map
        }
    return workspace_or_list


@server_workspaces_bp.route('', methods=['GET'])
@require_permission('org.workspaces:view')
@handle_route_exceptions('server_workspaces:get_workspaces')
def get_workspaces():
    """Get every workspace on the deployment.

    This is the administration listing and is not filtered per caller — reaching it at all
    requires org.workspaces:view. A user's own workspaces come from /workspaces/user/<id>.
    """
    workspaces = workspaces_db.get_all_workspaces()
    return jsonify(_with_device_names(workspaces)), 200


@server_workspaces_bp.route('/user/<user_id>', methods=['GET'])
@handle_route_exceptions('server_workspaces:get_user_workspaces')
def get_user_workspaces(user_id: str):
    """Get all workspaces a user has access to (direct + via team membership).

    Carries no permission gate because every signed-in principal calls it for themselves on
    every page load — WorkspaceProvider fetches the workspace switcher from here, so gating it
    on workspace administration would empty the switcher for testers and viewers.

    It takes the user id from the path, though, so it needs its own check: without one, any
    authenticated caller could read anyone else's workspace list by editing the URL. Reading
    for yourself is always allowed; reading for somebody else is workspace administration.
    """
    caller_id = getattr(request, 'user_id', None)

    # caller_id is None on a principal that carries no user identity (the service key, open
    # mode, auto-sign). Those are already trusted by the global guard to reach /server/*, and
    # have no "self" to compare against, so they pass.
    if caller_id and caller_id != user_id and not principal_holds_permission('org.workspaces:view'):
        return jsonify({
            'error': 'Forbidden',
            'message': 'You may only read your own workspaces.',
            'user_role': getattr(request, 'user_role', None),
        }), 403

    workspaces = workspaces_db.get_user_workspaces(user_id)
    return jsonify(_with_device_names(workspaces)), 200


@server_workspaces_bp.route('/<workspace_id>', methods=['GET'])
@require_permission('org.workspaces:view')
@handle_route_exceptions('server_workspaces:get_workspace')
def get_workspace(workspace_id: str):
    """Get a specific workspace by ID"""
    workspace = workspaces_db.get_workspace(workspace_id)
    if not workspace:
        return jsonify({"error": "Workspace not found"}), 404
    return jsonify(_with_device_names(workspace)), 200


@server_workspaces_bp.route('', methods=['POST'])
@require_permission('org.workspaces:create')
@handle_route_exceptions('server_workspaces:create_workspace')
def create_workspace():
    """Create a new workspace (org.workspaces:create)"""
    data = request.get_json() or {}
    if not data.get('name'):
        return jsonify({"error": "Workspace name is required"}), 400
    try:
        workspace = workspaces_db.create_workspace(data)
    except workspaces_db.DuplicateSlugError as e:
        # 409, not 500: the slug is derived from the name the caller sent, so a collision is
        # something they can act on. As a 500 it read as an outage — and it silently blocked
        # every rerun of the workspace tests, whose fixture used a fixed name.
        return jsonify({"error": str(e), "slug": e.slug}), 409
    if not workspace:
        return jsonify({"error": "Failed to create workspace"}), 500
    logger.info(f"Workspace created: {workspace['id']}")
    return jsonify(_with_device_names(workspace)), 201


@server_workspaces_bp.route('/<workspace_id>', methods=['PUT'])
@require_permission('org.workspaces:edit')
@handle_route_exceptions('server_workspaces:update_workspace')
def update_workspace(workspace_id: str):
    """Update a workspace (org.workspaces:edit)"""
    data = request.get_json() or {}
    if not data:
        return jsonify({"error": "No data provided"}), 400
    workspace = workspaces_db.update_workspace(workspace_id, data)
    if not workspace:
        return jsonify({"error": "Workspace not found"}), 404
    logger.info(f"Workspace updated: {workspace_id}")
    return jsonify(_with_device_names(workspace)), 200


@server_workspaces_bp.route('/<workspace_id>', methods=['DELETE'])
@require_permission('org.workspaces:delete')
@handle_route_exceptions('server_workspaces:delete_workspace')
def delete_workspace(workspace_id: str):
    """Delete a workspace (org.workspaces:delete)"""
    success = workspaces_db.delete_workspace(workspace_id)
    if not success:
        return jsonify({"error": "Workspace not found"}), 404
    logger.info(f"Workspace deleted: {workspace_id}")
    return jsonify({"message": "Workspace deleted successfully"}), 200


@server_workspaces_bp.route('/<workspace_id>/members', methods=['GET'])
@require_permission('org.workspaces:view')
@handle_route_exceptions('server_workspaces:get_workspace_members')
def get_workspace_members(workspace_id: str):
    """Get all members of a workspace (org.workspaces:view)"""
    members = workspaces_db.get_workspace_members(workspace_id)
    return jsonify(members), 200


@server_workspaces_bp.route('/<workspace_id>/members/user', methods=['POST'])
@require_permission('org.workspaces:manage_members')
@handle_route_exceptions('server_workspaces:add_workspace_user')
def add_workspace_user(workspace_id: str):
    """Add a user to a workspace (org.workspaces:manage_members)"""
    data = request.get_json() or {}
    if not data.get('user_id'):
        return jsonify({"error": "user_id is required"}), 400
    member = workspaces_db.add_workspace_user(workspace_id, data['user_id'], data.get('role', 'member'))
    if not member:
        return jsonify({"error": "Failed to add workspace user"}), 500
    logger.info(f"User {data['user_id']} added to workspace {workspace_id}")
    return jsonify(member), 201


@server_workspaces_bp.route('/<workspace_id>/members/team', methods=['POST'])
@require_permission('org.workspaces:manage_members')
@handle_route_exceptions('server_workspaces:add_workspace_team')
def add_workspace_team(workspace_id: str):
    """Add a team to a workspace (org.workspaces:manage_members)"""
    data = request.get_json() or {}
    if not data.get('team_id'):
        return jsonify({"error": "team_id is required"}), 400
    member = workspaces_db.add_workspace_team(workspace_id, data['team_id'], data.get('role', 'member'))
    if not member:
        return jsonify({"error": "Failed to add workspace team"}), 500
    logger.info(f"Team {data['team_id']} added to workspace {workspace_id}")
    return jsonify(member), 201


@server_workspaces_bp.route('/<workspace_id>/members/<member_id>', methods=['DELETE'])
@require_permission('org.workspaces:manage_members')
@handle_route_exceptions('server_workspaces:remove_workspace_member')
def remove_workspace_member(workspace_id: str, member_id: str):
    """Remove a member from a workspace (org.workspaces:manage_members)"""
    success = workspaces_db.remove_workspace_member(workspace_id, member_id)
    if not success:
        return jsonify({"error": "Failed to remove workspace member"}), 500
    logger.info(f"Member {member_id} removed from workspace {workspace_id}")
    return jsonify({"message": "Workspace member removed successfully"}), 200
