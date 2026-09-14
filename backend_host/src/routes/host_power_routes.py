"""
Host Power Routes

Host-side power control endpoints that execute power commands using instantiated power controllers.
"""

from flask import Blueprint, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_controller
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import (
    bad_request,
    controller_missing_for_device
)

# Create blueprint
host_power_bp = Blueprint('host_power', __name__, url_prefix='/host/power')

# =====================================================
# POWER CONTROLLER ENDPOINTS
# =====================================================

@host_power_bp.route('/getStatus', methods=['POST'])
@route_exception_handler()
def get_power_status():
    # Get device_id from request (defaults to device1)
    data = get_json_payload()
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_power:get_power_status] Getting power status for device: {device_id}")
    
    # Get power controller for the specified device
    power_controller = get_controller(device_id, 'power')

    if not power_controller:
        return controller_missing_for_device('power', device_id)
    
    print(f"[@route:host_power:get_power_status] Using power controller: {type(power_controller).__name__}")
    
    # Get power status from controller
    status = power_controller.get_power_status()
    
    return jsonify({
        'success': True,
        'status': status,
        'device_id': device_id
    })
        
@host_power_bp.route('/executeCommand', methods=['POST'])
@route_exception_handler()
def execute_power_command():
    data = get_json_payload()
    command, command_error = require_field(data, 'command', message='command is required')
    if command_error:
        return command_error

    params = data.get('params', {})
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:host_power:execute_power_command] Executing command: {command} with params: {params} for device: {device_id}")
    
    if not command:
        return jsonify({
            'success': False,
            'error': 'command is required'
        }), 400
    
    # Validate command
    valid_commands = ['power_on', 'power_off', 'reboot']
    if command not in valid_commands:
        return bad_request(f'Invalid command. Valid commands: {valid_commands}')
    
    # Get power controller for the specified device
    power_controller = get_controller(device_id, 'power')
    
    if not power_controller:
        return controller_missing_for_device('power', device_id)
    
    print(f"[@route:host_power:execute_power_command] Using power controller: {type(power_controller).__name__}")
    
    # Use controller-specific abstraction - single line!
    success = power_controller.execute_command(command, params)
    
    return jsonify({
        'success': success,
        'message': f'Command {command} {"executed successfully" if success else "failed"}',
        'device_id': device_id
    })
        
