"""
Server LoL overlay route: the stream modal's live overlay data, forwarded from the host.

The browser holds no host API key, so it asks the server (POST /server/lol-overlay/live {host_name});
the server calls the host's /host/lol-overlay/live through call_host(), which injects the key.
"""

from flask import Blueprint, jsonify, request

from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params

server_lol_overlay_bp = Blueprint('server_lol_overlay', __name__, url_prefix='/server/lol-overlay')


@server_lol_overlay_bp.route('/live', methods=['POST'])
def live():
    request_data = request.get_json() or {}
    if not request_data.get('host_name'):
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    response_data, status_code = proxy_to_host_with_params(
        '/host/lol-overlay/live', 'GET', request_data, {}, timeout=5,
    )
    return jsonify(response_data), status_code
