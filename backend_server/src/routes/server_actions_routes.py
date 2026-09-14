"""
Server Actions Routes - Action Execution Only

This module provides action execution endpoints.
Actions are now embedded directly in navigation edges, so no database CRUD operations are needed.
"""

from flask import Blueprint, request, jsonify

from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

# Create blueprint
server_actions_bp = Blueprint('server_actions', __name__, url_prefix='/server/action')

# =====================================================
# ACTION EXECUTION
# =====================================================

@server_actions_bp.route('/executeBatch', methods=['POST'])
@handle_route_exceptions('server_actions:executeBatch')
def action_execute_batch():
    """Execute batch of actions using ActionExecutor directly (same as navigation execution)"""
    print("[@route:server_actions:action_execute_batch] Starting batch action execution")
    data = request.get_json() or {}
    actions = data.get('actions', [])
    host_name = data.get('host_name')
    device_id = data.get('device_id', 'device1')
    retry_actions = data.get('retry_actions', [])
    failure_actions = data.get('failure_actions', [])
    team_id = request.args.get('team_id')
    tree_id = data.get('tree_id')
    edge_id = data.get('edge_id')
    action_set_id = data.get('action_set_id')
    target_node_id = data.get('target_node_id')
    current_node_id = data.get('current_node_id')
    userinterface_name = data.get('userinterface_name')

    # Run scope: lowercase variant name or None for base.
    raw_variant = data.get('variant')
    variant = (raw_variant or '').strip().lower() or None if isinstance(raw_variant, str) else None

    # Interactive Editor runs flag is_test=true so edge_metrics aggregates
    # exclude the row. Plumbed through to the host's NavigationExecutor.
    is_test = bool(data.get('is_test', False))

    # Per-edge settle delay (ms). Forwarded into the step dict by the host
    # so NavigationExecutor.execute_single_edge_step honors it the same way
    # a goto step does.
    try:
        final_wait_time = int(data.get('final_wait_time') or 0)
    except (TypeError, ValueError):
        final_wait_time = 0
    if final_wait_time < 0:
        final_wait_time = 0

    if not actions:
        return jsonify({'success': False, 'error': 'actions are required'}), 400
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    execution_payload = {
        'actions': actions,
        'retry_actions': retry_actions,
        'failure_actions': failure_actions,
        'device_id': device_id,
        'tree_id': tree_id,
        'edge_id': edge_id,
        'action_set_id': action_set_id,
        'target_node_id': target_node_id,
        'current_node_id': current_node_id,
        'userinterface_name': userinterface_name,
        'team_id': team_id,
        'variant': variant,
        'is_test': is_test,
        'final_wait_time': final_wait_time,
    }
    query_params = {}
    if device_id:
        query_params['device_id'] = device_id
    if team_id:
        query_params['team_id'] = team_id
    has_web_action = any(action.get('action_type') == 'web' for action in actions)
    timeout = 60 if has_web_action else 10
    response_data, status_code = proxy_to_host_with_params(
        '/host/action/executeBatch', 'POST', execution_payload, query_params, timeout=timeout
    )
    return jsonify(response_data), status_code
@server_actions_bp.route('/execution/<execution_id>/status', methods=['GET'])
@handle_route_exceptions('server_actions:get_status')
def get_action_execution_status(execution_id):
    """
    Get status of async action execution
    
    Query parameters:
    - device_id: Device ID
    - host_name: Host name (required)
    """
    print(f"[@route:server_actions:get_status] Getting status for execution {execution_id}")
    device_id = request.args.get('device_id')
    host_name = request.args.get('host_name')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name query parameter is required'}), 400
    query_params = {}
    if device_id:
        query_params['device_id'] = device_id
    response_data, status_code = proxy_to_host_with_params(
        f'/host/action/execution/{execution_id}/status', 'GET', None, query_params, timeout=5
    )
    return jsonify(response_data), status_code


@server_actions_bp.route('/abortExecution', methods=['POST'])
@handle_route_exceptions('server_actions:abortExecution')
def abort_action_execution():
    """Abort a running async action execution."""
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    execution_id = data.get('execution_id')
    team_id = request.args.get('team_id')

    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    if not execution_id:
        return jsonify({'success': False, 'error': 'execution_id is required'}), 400

    payload = {
        'host_name': host_name,
        'device_id': device_id,
        'execution_id': execution_id,
    }
    query_params = {}
    if device_id:
        query_params['device_id'] = device_id
    if team_id:
        query_params['team_id'] = team_id

    response_data, status_code = proxy_to_host_with_params(
        '/host/action/abortExecution', 'POST', payload, query_params, timeout=10
    )
    return jsonify(response_data), status_code


@server_actions_bp.route('/execute', methods=['POST'])
@handle_route_exceptions('server_actions:execute')
def action_execute_single():
    """Execute a single action with embedded action object"""
    print("[@route:server_actions:action_execute_single] Starting single command execution")
    data = request.get_json() or {}
    action = data.get('action', {})
    host_name = data.get('host_name')
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')

    raw_variant = data.get('variant')
    variant = (raw_variant or '').strip().lower() or None if isinstance(raw_variant, str) else None

    if not action:
        return jsonify({'success': False, 'error': 'action is required'}), 400
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    execution_payload = {
        'actions': [action],
        'device_id': device_id,
        'retry_actions': [],
        'team_id': team_id,
        'variant': variant,
    }
    query_params = {}
    if device_id:
        query_params['device_id'] = device_id
    if team_id:
        query_params['team_id'] = team_id
    response_data, status_code = proxy_to_host_with_params(
        '/host/action/executeBatch', 'POST', execution_payload, query_params, timeout=10
    )
    return jsonify(response_data), status_code


# =====================================================
# HEALTH CHECK
# =====================================================

@server_actions_bp.route('/checkDependenciesBatch', methods=['POST'])
@handle_route_exceptions('server_actions:checkDependenciesBatch')
def check_dependencies_batch():
    """Check if actions are used in other edges (dependency check) - DEPRECATED: Legacy action_ids removed"""
    return jsonify({
        'success': True,
        'has_shared_actions': False,
        'edges': [],
        'count': 0,
        'message': 'Dependency check completed - no shared actions found'
    })

@server_actions_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for action execution service"""
    return jsonify({
        'success': True,
        'message': 'Action execution service is running',
        'note': 'Actions are now embedded in navigation edges'
    })


 
