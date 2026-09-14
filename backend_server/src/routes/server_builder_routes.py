"""
Server Builder Routes - Proxy for Standard Block Execution

Proxies standard block execution requests to host.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params

# Create blueprint
server_builder_bp = Blueprint('server_builder', __name__, url_prefix='/server/builder')


@server_builder_bp.route('/execute', methods=['POST'])
@handle_route_exceptions('builder:execute_standard_block')
def execute_standard_block():
    """
    Execute a standard block asynchronously (sleep, loop, set_variable, etc.)
    Returns execution_id immediately for socket-based completion tracking.
    
    Proxies to /host/builder/execute (which returns execution_id)
    
    Request body:
        {
            "command": "sleep",
            "params": {"duration": 2.0},
            "host_name": "pi1",
            "device_id": "device1"
        }
    
    Returns:
        {
            "success": true,
            "execution_id": "...",
            "message": "Block execution started"
        }
    """
    print("[@route:server_builder:execute] Starting async standard block execution")
    
    # Get request data
    data = request.get_json() or {}
    command = data.get('command')
    params = data.get('params', {})
    host_name = data.get('host_name')
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    
    print(f"[@route:server_builder:execute] Executing block: {command}")
    print(f"[@route:server_builder:execute] Host: {host_name}, Device: {device_id}")
    
    # Validate
    if not command:
        return jsonify({'success': False, 'error': 'command is required'}), 400
    
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Prepare execution payload
    execution_payload = {
        'command': command,
        'params': params,
        'device_id': device_id
    }
    
    # Query params
    query_params = {'team_id': team_id}
    if device_id:
        query_params['device_id'] = device_id
    
    print(f"[@route:server_builder:execute] Proxying to host (async)...")
    
    # Proxy to host - now returns execution_id immediately
    response_data, status_code = proxy_to_host_with_params(
        '/host/builder/execute',
        'POST',
        execution_payload,
        query_params,
        timeout=10  # Quick timeout since this just starts execution
    )
    
    if response_data.get('success'):
        print(f"[@route:server_builder:execute] Block execution started: {response_data.get('execution_id')}")
    else:
        print(f"[@route:server_builder:execute] Failed to start: {response_data.get('error', 'Unknown error')}")
    
    return jsonify(response_data), status_code
    
@server_builder_bp.route('/execution/<execution_id>/status', methods=['GET'])
@handle_route_exceptions('builder:get_execution_status')
def get_execution_status(execution_id):
    """
    Get status of async standard block execution
    
    Query params:
        - host_name: Host to check status on
        - device_id: Device ID
        - team_id: Team ID
    
    Returns:
        {
            "success": true,
            "status": "completed",  # or "running", "error"
            "result": {...},         # Only when completed
            "error": "...",          # Only when error
            "progress": 50,          # 0-100
            "message": "..."
        }
    """
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    
    print(f"[@route:server_builder:status] Checking status: {execution_id}")
    
    # Validate
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Query params
    query_params = {
        'team_id': team_id,
        'device_id': device_id
    }
    
    # Proxy to host status endpoint
    response_data, status_code = proxy_to_host_with_params(
        f'/host/builder/execution/{execution_id}/status',
        'GET',
        None,
        query_params,
        timeout=5
    )
    
    return jsonify(response_data), status_code
    
