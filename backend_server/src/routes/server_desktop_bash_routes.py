"""
Server Desktop Bash Routes

Server-side bash desktop endpoints that proxy requests to host bash desktop endpoints.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from  backend_server.src.lib.utils.route_utils import proxy_to_host

# Create blueprint
server_desktop_bash_bp = Blueprint('server_desktop_bash', __name__, url_prefix='/server/desktop/bash')

@server_desktop_bash_bp.route('/executeCommand', methods=['POST'])
@handle_route_exceptions('desktop_bash:desktop_bash_execute')
def desktop_bash_execute():
    """Proxy bash desktop command execution to host"""
    print("[@route:server_desktop_bash:execute_command] Proxying bash desktop request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Proxy to host bash desktop endpoint
    response_data, status_code = proxy_to_host('/host/desktop/bash/executeCommand', 'POST', request_data, timeout=60)
    
    return jsonify(response_data), status_code
    