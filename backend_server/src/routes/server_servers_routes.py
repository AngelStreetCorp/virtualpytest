"""
Platform server list routes (TASK-179).

  GET /server/servers   any authenticated user  -> {servers, self_name, self_in_list, warning}
  PUT /server/servers   platform admin only     -> replaces the list, body {servers: [{name, url, enabled?, sort_order?}]}

The list lives in ``platform_servers`` (platform-level, no team_id). Each server caches it 60 s; a PUT invalidates the cache of the
server that handled it, the others pick it up within 60 s.
"""

import logging

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_platform_admin
from backend_server.src.lib.servers import registry
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database import platform_servers_db

server_servers_bp = Blueprint('server_servers', __name__, url_prefix='/server/servers')
logger = logging.getLogger(__name__)


def _warning() -> str:
    if registry.table_missing():
        return 'server list table missing on this database'
    me = registry.self_name()
    if me is None:
        return 'SERVER_NAME is not set (or is a default value) on this server: it cannot find itself in the server list'
    if not registry.self_in_list():
        return f'this server ("{me}") is not in the server list: SERVER_NAME must match a row name'
    return ''


def _payload(rows):
    return {
        'success': True,
        'servers': [{k: r.get(k) for k in ('name', 'url', 'enabled', 'sort_order')} for r in rows],
        'self_name': registry.self_name(),
        'self_in_list': registry.self_in_list(),
        'warning': _warning() or None,
    }


@server_servers_bp.route('', methods=['GET'])
@handle_route_exceptions('servers')
def list_platform_servers():
    return jsonify(_payload(registry.servers()))


@server_servers_bp.route('', methods=['PUT'])
@require_platform_admin
@handle_route_exceptions('servers')
def replace_platform_servers():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or 'servers' not in body:
        return jsonify({'success': False, 'error': 'body must be {"servers": [...]}'}), 400
    try:
        platform_servers_db.replace_servers(body['servers'])
    except platform_servers_db.InvalidServers as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except platform_servers_db.TableMissing:
        return jsonify({'success': False, 'error': 'server list table missing on this database'}), 503
    registry.invalidate()
    return jsonify(_payload(registry.servers()))
