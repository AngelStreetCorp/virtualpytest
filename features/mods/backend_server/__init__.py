"""
mods feature — backend_server part (TASK-77, docs/agent/platform/MODS.md).

Registered by shared/src/lib/utils/features.py when the feature is enabled. Everything
lives under /server/mods:

  GET  /server/mods/snapshot?team_id=      the current state as /system updates (runs, locks, presence)
  GET  /server/mods/preferences?team_id=   this user's mod on/off choices in this team
  PUT  /server/mods/preferences            {team_id, mod_id, enabled}
  GET  /server/mods/widgets?team_id=&area= this user's widget layout of an area (null = never saved)
  PUT  /server/mods/widgets                {team_id, area, layout}

team_id is checked against the caller's teams by the global enforce_team_scope guard.
A shared login (service key, auto-sign, open mode, public key) is not one person: it gets
`shared: true` and no stored choices, and the browser keeps its own.
"""

import uuid
from typing import Optional

from flask import Blueprint, jsonify, request

from backend_server.src.lib import socket_presence
from backend_server.src.lib.utils.lock_utils import get_device_lock_manager
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions, require_team_id_from_args
from backend_server.src.lib.utils.task_manager import task_manager

from features.mods.lib import mods_db
from features.mods.lib.snapshot import build_snapshot
from features.mods.lib.widget_layout import clean_layout, valid_area

feature_mods_bp = Blueprint('feature_mods', __name__, url_prefix='/server/mods')


def _person_id() -> Optional[str]:
    """The caller's user id when it is one person (a UUID), else None for a shared login."""
    user_id = getattr(request, 'user_id', None)
    try:
        return str(uuid.UUID(str(user_id)))
    except (TypeError, ValueError):
        return None


@feature_mods_bp.route('/snapshot', methods=['GET'])
@handle_route_exceptions('feature_mods:snapshot')
def snapshot():
    team_id, err = require_team_id_from_args()
    if err:
        return err
    events = build_snapshot(
        task_manager.running_tasks('script_execute', team_id),
        get_device_lock_manager().get_all_locked_devices(),
        socket_presence.snapshot(team_id),
    )
    return jsonify({'success': True, 'events': events})


@feature_mods_bp.route('/preferences', methods=['GET'])
@handle_route_exceptions('feature_mods:get_preferences')
def get_preferences():
    team_id, err = require_team_id_from_args()
    if err:
        return err
    user_id = _person_id()
    if not user_id:
        return jsonify({'success': True, 'shared': True, 'choices': {}})
    return jsonify({'success': True, 'shared': False, 'choices': mods_db.get_choices(team_id, user_id)})


@feature_mods_bp.route('/preferences', methods=['PUT'])
@handle_route_exceptions('feature_mods:set_preference')
def set_preference():
    data = request.get_json(silent=True) or {}
    team_id = data.get('team_id')
    mod_id = data.get('mod_id')
    enabled = data.get('enabled')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if not mods_db.valid_mod_id(mod_id) or not isinstance(enabled, bool):
        return jsonify({'success': False, 'error': 'mod_id (text) and enabled (boolean) are required'}), 400
    user_id = _person_id()
    if not user_id:
        return jsonify({'success': False, 'shared': True, 'error': 'A shared login keeps its choices in the browser'}), 409
    mods_db.set_choice(team_id, user_id, mod_id.strip(), enabled)
    return jsonify({'success': True})


@feature_mods_bp.route('/widgets', methods=['GET'])
@handle_route_exceptions('feature_mods:get_widgets')
def get_widgets():
    team_id, err = require_team_id_from_args()
    if err:
        return err
    area = request.args.get('area')
    if not valid_area(area):
        return jsonify({'success': False, 'error': 'unknown area'}), 400
    user_id = _person_id()
    if not user_id:
        return jsonify({'success': True, 'shared': True, 'layout': None})
    return jsonify({'success': True, 'shared': False, 'layout': mods_db.get_widget_layout(team_id, user_id, area)})


@feature_mods_bp.route('/widgets', methods=['PUT'])
@handle_route_exceptions('feature_mods:set_widgets')
def set_widgets():
    data = request.get_json(silent=True) or {}
    team_id = data.get('team_id')
    area = data.get('area')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if not valid_area(area):
        return jsonify({'success': False, 'error': 'unknown area'}), 400
    layout, why = clean_layout(data.get('layout'))
    if layout is None:
        return jsonify({'success': False, 'error': why}), 400
    user_id = _person_id()
    if not user_id:
        return jsonify({'success': False, 'shared': True, 'error': 'A shared login keeps its layout in the browser'}), 409
    mods_db.set_widget_layout(team_id, user_id, area, layout)
    return jsonify({'success': True})


def register(app):
    app.register_blueprint(feature_mods_bp)
