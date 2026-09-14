"""
Host Desktop Bash Routes

Host-side bash desktop endpoints that execute using instantiated bash desktop controllers.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_handlers import get_desktop_controller

# Create blueprint
host_desktop_bash_bp = Blueprint('host_desktop_bash', __name__, url_prefix='/host/desktop/bash')

@host_desktop_bash_bp.route('/executeCommand', methods=['POST'])
@route_exception_handler()
def execute_bash_command():
    print("[@route:host_desktop_bash:execute_command] Executing bash desktop command")
    
    # Get request data
    data = request.get_json() or {}
    command = data.get('command')
    params = data.get('params', {})
    device_id = data.get('device_id')  # Optional, defaults to host
    
    print(f"[@route:host_desktop_bash:execute_command] Command: {command}, Params: {params}")
    
    if not command:
        return jsonify({
            'success': False,
            'error': 'command is required'
        }), 400
    
    # Get bash desktop controller
    controller, device, error_response = get_desktop_controller(
        device_id,
        'desktop',
        desktop_keywords=('bash',),
        display_name='bash',
    )
    if error_response:
        return error_response
    
    print(f"[@route:host_desktop_bash:execute_command] Using controller: {type(controller).__name__}")
    
    # Execute command using controller
    result = controller.execute_command(command, params)
    
    print(f"[@route:host_desktop_bash:execute_command] Command result: success={result.get('success', False)}")
    
    return jsonify(result)
    
