"""
Server routes for team-scoped library visibility controls.
"""

from flask import Blueprint, jsonify, request

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.routes.server_campaign_routes import invalidate_campaign_executable_cache
from backend_server.src.routes.server_executable_routes import invalidate_executable_list_cache
from backend_server.src.routes.server_script_routes import invalidate_script_list_cache
from shared.src.lib.database.library_visibility_db import (
    VALID_ENTITY_TYPES,
    hide_library_item,
    list_library_visibility,
    show_library_item,
)

server_library_visibility_bp = Blueprint(
    'server_library_visibility',
    __name__,
    url_prefix='/server/library-visibility',
)


def _invalidate_visibility_consumers() -> None:
    invalidate_campaign_executable_cache()
    invalidate_executable_list_cache()
    invalidate_script_list_cache()


@server_library_visibility_bp.route('/list', methods=['GET'])
@handle_route_exceptions('library_visibility:list')
def list_library_visibility_route():
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    entity_type = request.args.get('entity_type')
    if entity_type and entity_type not in VALID_ENTITY_TYPES:
        return jsonify({'success': False, 'error': f'entity_type must be one of {sorted(VALID_ENTITY_TYPES)}'}), 400
    rules = list_library_visibility(team_id, entity_type)
    return jsonify({'success': True, 'items': rules})


@server_library_visibility_bp.route('/hide', methods=['POST'])
@handle_route_exceptions('library_visibility:hide')
def hide_library_visibility_route():
    team_id = request.args.get('team_id')
    data = request.get_json() or {}
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    entity_type = data.get('entity_type')
    entity_key = data.get('entity_key')
    if not entity_type or not entity_key:
        return jsonify({'success': False, 'error': 'entity_type and entity_key are required'}), 400
    if entity_type not in VALID_ENTITY_TYPES:
        return jsonify({'success': False, 'error': f'entity_type must be one of {sorted(VALID_ENTITY_TYPES)}'}), 400

    success = hide_library_item(team_id, entity_type, entity_key, data.get('updated_by'))
    if not success:
        return jsonify({'success': False, 'error': 'Failed to hide library item'}), 500

    _invalidate_visibility_consumers()
    return jsonify({'success': True})


@server_library_visibility_bp.route('/show', methods=['POST'])
@handle_route_exceptions('library_visibility:show')
def show_library_visibility_route():
    team_id = request.args.get('team_id')
    data = request.get_json() or {}
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    entity_type = data.get('entity_type')
    entity_key = data.get('entity_key')
    if not entity_type or not entity_key:
        return jsonify({'success': False, 'error': 'entity_type and entity_key are required'}), 400
    if entity_type not in VALID_ENTITY_TYPES:
        return jsonify({'success': False, 'error': f'entity_type must be one of {sorted(VALID_ENTITY_TYPES)}'}), 400

    success = show_library_item(team_id, entity_type, entity_key)
    if not success:
        return jsonify({'success': False, 'error': 'Failed to show library item'}), 500

    _invalidate_visibility_consumers()
    return jsonify({'success': True})
