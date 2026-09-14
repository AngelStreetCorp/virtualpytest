"""
Agent Runtime REST API Routes

Provides HTTP endpoints for agent instance management, status, and control.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from typing import Optional
import asyncio

from agent.runtime import AgentRuntime, get_agent_runtime
from events import get_event_bus
from agent.async_utils import run_async
from backend_server.src.routes.server_system_socket_routes import emit_system_update

# Create blueprint
server_agent_runtime_bp = Blueprint('server_agent_runtime', __name__, url_prefix='/server/runtime')


def _emit_runtime_update(update_type: str, instance_id: Optional[str] = None, team_id: Optional[str] = None):
    payload = {'domain': 'agent_runtime'}
    if instance_id:
        payload['instance_id'] = instance_id
    if team_id:
        payload['team_id'] = team_id
    emit_system_update(update_type, payload)


def get_team_id() -> str:
    """Get team ID from request"""
    return request.headers.get('X-Team-ID', 'default')


@server_agent_runtime_bp.route('/instances', methods=['GET'])
@handle_route_exceptions('agent_runtime:list_instances')
def list_instances():
    """
    List all running agent instances
    
    Query params:
        - team_id: Filter by team
    """
    team_id = request.args.get('team_id', get_team_id())
    runtime = get_agent_runtime()
    instances = runtime.list_instances(team_id)
    return jsonify({'instances': instances, 'count': len(instances)}), 200


@server_agent_runtime_bp.route('/instances/<instance_id>', methods=['GET'])
@handle_route_exceptions('agent_runtime:get_instance_status')
def get_instance_status(instance_id: str):
    """Get status of specific agent instance"""
    runtime = get_agent_runtime()
    status = runtime.get_status(instance_id)
    if not status:
        return jsonify({'error': 'Instance not found'}), 404
    return jsonify(status), 200


@server_agent_runtime_bp.route('/instances/start', methods=['POST'])
@handle_route_exceptions('agent_runtime:start_agent_instance')
def start_agent_instance():
    """
    Start new agent instance
    
    Body:
        - agent_id: Agent to start (required)
        - version: Version (optional, defaults to latest)
        - team_id: Team namespace (optional)
    """
    data = request.get_json() or {}
    if not data or 'agent_id' not in data:
        return jsonify({'error': 'agent_id required'}), 400
    agent_id = data['agent_id']
    version = data.get('version')
    team_id = data.get('team_id', get_team_id())
    runtime = get_agent_runtime()
    if not runtime._running:
        run_async(runtime.start())
    try:
        instance_id = run_async(runtime.start_agent(agent_id, version, team_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    _emit_runtime_update('agent_runtime_instance_started', instance_id=instance_id, team_id=team_id)
    return jsonify({'instance_id': instance_id, 'message': 'Agent started successfully'}), 201


@server_agent_runtime_bp.route('/instances/<instance_id>/stop', methods=['POST'])
@handle_route_exceptions('agent_runtime:stop_agent_instance')
def stop_agent_instance(instance_id: str):
    """Stop agent instance"""
    runtime = get_agent_runtime()
    success = run_async(runtime.stop_agent(instance_id))
    if success:
        _emit_runtime_update('agent_runtime_instance_stopped', instance_id=instance_id)
        return jsonify({'message': 'Agent stopped successfully'}), 200
    return jsonify({'error': 'Instance not found'}), 404


@server_agent_runtime_bp.route('/instances/<instance_id>/pause', methods=['POST'])
@handle_route_exceptions('agent_runtime:pause_agent_instance')
def pause_agent_instance(instance_id: str):
    """Pause agent instance"""
    runtime = get_agent_runtime()
    success = run_async(runtime.pause_agent(instance_id))
    if success:
        _emit_runtime_update('agent_runtime_instance_paused', instance_id=instance_id)
        return jsonify({'message': 'Agent paused successfully'}), 200
    return jsonify({'error': 'Instance not found or cannot be paused'}), 400


@server_agent_runtime_bp.route('/instances/<instance_id>/resume', methods=['POST'])
@handle_route_exceptions('agent_runtime:resume_agent_instance')
def resume_agent_instance(instance_id: str):
    """Resume paused agent instance"""
    runtime = get_agent_runtime()
    success = run_async(runtime.resume_agent(instance_id))
    if success:
        _emit_runtime_update('agent_runtime_instance_resumed', instance_id=instance_id)
        return jsonify({'message': 'Agent resumed successfully'}), 200
    return jsonify({'error': 'Instance not found or not paused'}), 400


@server_agent_runtime_bp.route('/start', methods=['POST'])
@handle_route_exceptions('agent_runtime:start_runtime')
def start_runtime():
    """Start the agent runtime system"""
    runtime = get_agent_runtime()
    if runtime._running:
        return jsonify({'message': 'Runtime already running'}), 200
    run_async(runtime.start())
    _emit_runtime_update('agent_runtime_started')
    return jsonify({'message': 'Runtime started successfully'}), 200


@server_agent_runtime_bp.route('/stop', methods=['POST'])
@handle_route_exceptions('agent_runtime:stop_runtime')
def stop_runtime():
    """Stop the agent runtime system"""
    runtime = get_agent_runtime()
    if not runtime._running:
        return jsonify({'message': 'Runtime not running'}), 200
    run_async(runtime.stop())
    _emit_runtime_update('agent_runtime_stopped')
    return jsonify({'message': 'Runtime stopped successfully'}), 200


@server_agent_runtime_bp.route('/status', methods=['GET'])
@handle_route_exceptions('agent_runtime:get_runtime_status')
def get_runtime_status():
    """Get overall runtime status"""
    runtime = get_agent_runtime()
    event_bus = get_event_bus()
    return jsonify({
        'running': runtime._running,
        'total_instances': len(runtime.instances),
        'active_tasks': len(runtime.tasks),
        'event_bus_connected': event_bus.redis_client is not None
    }), 200


# WebSocket endpoint for real-time status updates
# Note: This would require additional WebSocket support
# For now, clients can poll the status endpoints
