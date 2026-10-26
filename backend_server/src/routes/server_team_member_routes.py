"""
Team-member routes (TASK-65 — heartbeats for Active Users)
==========================================================

`PUT /server/team/last_seen` — the caller's app pings this every 60 s (client-side
throttle) to refresh `team_members.last_seen_at`. The db layer is idempotent
(only writes if `last_seen_at IS NULL OR last_seen_at < now() - 60 s`).

Service key / auto-signed / open mode callers are no-ops: the Active Users tile is
about signed-in team members, not the service key.
"""

import logging

from flask import Blueprint, request, jsonify

from shared.src.lib.database import projects_db
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions


logger = logging.getLogger(__name__)


server_team_member_bp = Blueprint('server_team_member', __name__, url_prefix='/server/team')


@server_team_member_bp.route('/last_seen', methods=['PUT'])
@handle_route_exceptions('server_team_member:touch_last_seen')
def touch_last_seen():
    """Idempotent heartbeat. Updates the caller's `team_members.last_seen_at`.

    For admins / service-key / auto-signed callers we return 200 with
    `updated_rows=0`: the heartbeat is about signed-in users, not the platform
    itself. The dashboard's Active Users count ignores these rows anyway (they
    have no `team_members.id` from the user side).
    """
    user_id = getattr(request, 'user_id', None)
    if not user_id or user_id in ('auto_signed', 'service_api_key', 'open_mode', 'public_key'):
        return jsonify({'updated_rows': 0, 'reason': 'non_user_principal'}), 200

    rows = projects_db.list_team_members_for_user(user_id)
    if not rows:
        return jsonify({'updated_rows': 0, 'reason': 'no_team_membership'}), 200

    updated = 0
    for row in rows:
        if projects_db.update_team_member_last_seen(row['id']):
            updated += 1
    return jsonify({'updated_rows': updated}), 200