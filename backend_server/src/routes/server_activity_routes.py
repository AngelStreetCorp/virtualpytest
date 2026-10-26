"""Activity feed (TASK-127 G6): read-only view over the existing audit tables.

  GET /server/activity?team_id=&q=&event=&actor=&since=&limit=
      -> {success, rows: [{at, event, tone, target, details, actor, source}], total, counts, actors}

Admin only, like the other Logs tabs. Records nothing.
"""
from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_role, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.activity_db import list_activity
from shared.src.lib.utils.app_utils import get_team_id

server_activity_bp = Blueprint('server_activity', __name__, url_prefix='/server/activity')


@server_activity_bp.route('', methods=['GET'])
@require_user_auth
@require_role('admin')
@handle_route_exceptions('activity')
def get_activity():
    team_id = request.args.get('team_id') or get_team_id()
    try:
        limit = int(request.args.get('limit', 200))
    except ValueError:
        limit = 200
    result = list_activity(
        team_id,
        q=request.args.get('q', ''),
        event=request.args.get('event', ''),
        actor=request.args.get('actor', ''),
        since=request.args.get('since'),
        limit=limit,
    )
    return jsonify({'success': True, **result})
