"""
Device Favorites Routes (TASK-99) — per-user stars on devices.

GET    /server/device-favorites?team_id=                       -> {favorites: [{host_name, device_id}]}
PUT    /server/device-favorites   {team_id, host_name, device_id}
DELETE /server/device-favorites   {team_id, host_name, device_id}  (or the same as query params)

Any logged-in role may star, viewer included: the path is in VIEWER_WRITE_EXEMPT_PREFIXES, because a
favorite is the caller's own preference and changes nothing shared. The user comes from the
verified principal (request.user_id), never from the request, so nobody edits another user's stars.
"""
from flask import Blueprint, request, jsonify

from shared.src.lib.database import device_favorites_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_device_favorites_bp = Blueprint(
    'server_device_favorites', __name__, url_prefix='/server/device-favorites'
)


def _param(name: str) -> str:
    """A field from the JSON body, else the query string (DELETE bodies are dropped by some proxies)."""
    body = request.get_json(silent=True) or {}
    return str(body.get(name) or request.args.get(name) or '').strip()


def _user_id():
    return str(getattr(request, 'user_id', '') or '').strip()


def _no_user():
    return jsonify({'success': False, 'error': 'Favorites belong to a signed-in user'}), 403


@server_device_favorites_bp.route('', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('device_favorites:list')
def list_favorites():
    team_id = _param('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    user_id = _user_id()
    if not user_id:
        return _no_user()
    return jsonify({'success': True, 'favorites': device_favorites_db.list_favorites(team_id, user_id)})


def _write(action):
    team_id, host_name, device_id = _param('team_id'), _param('host_name'), _param('device_id')
    if not (team_id and host_name and device_id):
        return jsonify({'success': False, 'error': 'team_id, host_name and device_id are required'}), 400
    user_id = _user_id()
    if not user_id:
        return _no_user()
    action(team_id, user_id, host_name, device_id)
    return jsonify({'success': True})


@server_device_favorites_bp.route('', methods=['PUT'], strict_slashes=False)
@handle_route_exceptions('device_favorites:add')
def add_favorite():
    return _write(device_favorites_db.add_favorite)


@server_device_favorites_bp.route('', methods=['DELETE'], strict_slashes=False)
@handle_route_exceptions('device_favorites:remove')
def remove_favorite():
    return _write(device_favorites_db.remove_favorite)
