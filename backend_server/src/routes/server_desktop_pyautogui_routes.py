"""
Server Desktop PyAutoGUI Routes

Server-side PyAutoGUI desktop endpoints that proxy requests to host PyAutoGUI desktop endpoints.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from  backend_server.src.lib.utils.route_utils import proxy_to_host

# Create blueprint
server_desktop_pyautogui_bp = Blueprint('server_desktop_pyautogui', __name__, url_prefix='/server/desktop/pyautogui')

@server_desktop_pyautogui_bp.route('/executeCommand', methods=['POST'])
@handle_route_exceptions('desktop_pyautogui:desktop_pyautogui_execute')
def desktop_pyautogui_execute():
    """Proxy PyAutoGUI desktop command execution to host"""
    print("[@route:server_desktop_pyautogui:execute_command] Proxying PyAutoGUI desktop request")
    
    # Get request data
    request_data = request.get_json() or {}
    
    # Proxy to host PyAutoGUI desktop endpoint
    response_data, status_code = proxy_to_host('/host/desktop/pyautogui/executeCommand', 'POST', request_data, timeout=60)
    
    return jsonify(response_data), status_code
    