"""
Executable Favorites Routes (TASK-100) — per-user stars on scripts, test cases, virtual scripts, campaigns.

GET    /server/executable-favorites?team_id=[&kind=]            -> {favorites: [{kind, item_id}]}
PUT    /server/executable-favorites   {team_id, kind, item_id}
DELETE /server/executable-favorites   {team_id, kind, item_id}  (or the same as query params)

kind is script | testcase | virtual_script | campaign (CONTRACTS #35). Any logged-in role may star,
viewer included: the path is in VIEWER_WRITE_EXEMPT_PREFIXES, because a favorite is the caller's own
preference and changes nothing shared. The user comes from the verified principal (request.user_id),
never from the request, so nobody edits another user's stars.
"""
from flask import Blueprint, request, jsonify

from shared.src.lib.database import executable_favorites_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_executable_favorites_bp = Blueprint(
    'server_executable_favorites', __name__, url_prefix='/server/executable-favorites'
)


def _param(name: str) -> str:
    """A field from the JSON body, else the query string (DELETE bodies are dropped by some proxies)."""
    body = request.get_json(silent=True) or {}
    return str(body.get(name) or request.args.get(name) or '').strip()


def _user_id():
    return str(getattr(request, 'user_id', '') or '').strip()


def _no_user():
    return jsonify({'success': False, 'error': 'Favorites belong to a signed-in user'}), 403


def _bad_kind():
    kinds = ', '.join(executable_favorites_db.KINDS)
    return jsonify({'success': False, 'error': f'kind must be one of: {kinds}'}), 400


@server_executable_favorites_bp.route('', methods=['GET'], strict_slashes=False)
@handle_route_exceptions('executable_favorites:list')
def list_favorites():
    team_id, kind = _param('team_id'), _param('kind')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if kind and kind not in executable_favorites_db.KINDS:
        return _bad_kind()
    user_id = _user_id()
    if not user_id:
        return _no_user()
    return jsonify({'success': True, 'favorites': executable_favorites_db.list_favorites(team_id, user_id, kind or None)})


def _write(action):
    team_id, kind, item_id = _param('team_id'), _param('kind'), _param('item_id')
    if not (team_id and kind and item_id):
        return jsonify({'success': False, 'error': 'team_id, kind and item_id are required'}), 400
    if kind not in executable_favorites_db.KINDS:
        return _bad_kind()
    user_id = _user_id()
    if not user_id:
        return _no_user()
    action(team_id, user_id, kind, item_id)
    return jsonify({'success': True})


@server_executable_favorites_bp.route('', methods=['PUT'], strict_slashes=False)
@handle_route_exceptions('executable_favorites:add')
def add_favorite():
    return _write(executable_favorites_db.add_favorite)


@server_executable_favorites_bp.route('', methods=['DELETE'], strict_slashes=False)
@handle_route_exceptions('executable_favorites:remove')
def remove_favorite():
    return _write(executable_favorites_db.remove_favorite)
