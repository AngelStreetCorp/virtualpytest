"""
Event System REST API Routes

Provides HTTP endpoints for manual event triggering and event statistics.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

from events import Event, EventPriority, get_event_bus
from events.event_router import EventRouter, get_event_router
from agent.async_utils import run_async

# Create blueprint.
# /server/events, not /api/events: nginx proxies only /server/* to the backend, so at the old
# prefix every route here fell through to the frontend SPA on the public deployment — an alert
# POST got 200 and a page of HTML, and read it as success. /server/* is also what app.py's JWT
# guard gates, so the old prefix left these open as well.
server_event_bp = Blueprint('server_events', __name__, url_prefix='/server/events')


def get_team_id() -> str:
    """Get team ID from request"""
    return request.args.get('team_id', request.headers.get('X-Team-ID', 'default'))


@server_event_bp.route('/publish', methods=['POST'])
@handle_route_exceptions('event:publish_event')
def publish_event():
    """
    Manually publish an event
    
    Body:
        - type: Event type (required)
        - payload: Event payload (required)
        - priority: Priority level (optional, default: normal)
    """
    data = request.get_json()
    
    if not data or 'type' not in data or 'payload' not in data:
        return jsonify({'error': 'type and payload required'}), 400
    
    team_id = data.get('team_id', get_team_id())
    
    # Parse priority
    priority_str = data.get('priority', 'normal').upper()
    try:
        priority = EventPriority[priority_str]
    except KeyError:
        priority = EventPriority.NORMAL
    
    # Create event
    event = Event(
        type=data['type'],
        payload=data['payload'],
        priority=priority,
        team_id=team_id
    )
    
    # Publish via router (async - needs run_async for Redis pub/sub)
    router = get_event_router()
    success = run_async(router.route_event(event))
    
    return jsonify({
        'event_id': event.id,
        'routed': success,
        'message': 'Event published successfully'
    }), 201
    
@server_event_bp.route('/types', methods=['GET'])
@handle_route_exceptions('event:list_event_types')
def list_event_types():
    """List all event types seen in the system"""
    team_id = get_team_id()
    
    router = get_event_router()
    event_types = router.get_event_types(team_id)  # Now sync
    
    return jsonify({
        'event_types': event_types,
        'count': len(event_types)
    }), 200
    
@server_event_bp.route('/stats', methods=['GET'])
@handle_route_exceptions('event:get_event_stats')
def get_event_stats():
    """Get event routing statistics"""
    team_id = get_team_id()
    
    router = get_event_router()
    stats = router.get_routing_stats(team_id)  # Now sync
    
    return jsonify(stats), 200
    
# Alert event shortcuts
@server_event_bp.route('/alerts/blackscreen', methods=['POST'])
@handle_route_exceptions('event:emit_blackscreen_alert')
def emit_blackscreen_alert():
    """
    Emit blackscreen alert event
    
    Body:
        - device_id: Device identifier (required)
    """
    data = request.get_json()
    
    if not data or 'device_id' not in data:
        return jsonify({'error': 'device_id required'}), 400
    
    team_id = data.get('team_id', get_team_id())
    
    event = Event(
        type="alert.blackscreen",
        payload={
            "device_id": data['device_id'],
            "severity": "critical"
        },
        priority=EventPriority.CRITICAL,
        team_id=team_id
    )
    
    router = get_event_router()
    success = run_async(router.route_event(event))
    
    return jsonify({
        'event_id': event.id,
        'routed': success,
        'message': 'Blackscreen alert published'
    }), 201
    
@server_event_bp.route('/alerts/device-offline', methods=['POST'])
@handle_route_exceptions('event:emit_device_offline_alert')
def emit_device_offline_alert():
    """
    Emit device offline alert event
    
    Body:
        - device_id: Device identifier (required)
        - duration_seconds: Offline duration (optional)
    """
    data = request.get_json()
    
    if not data or 'device_id' not in data:
        return jsonify({'error': 'device_id required'}), 400
    
    team_id = data.get('team_id', get_team_id())
    
    event = Event(
        type="alert.device_offline",
        payload={
            "device_id": data['device_id'],
            "duration_seconds": data.get('duration_seconds', 300),
            "severity": "high"
        },
        priority=EventPriority.HIGH,
        team_id=team_id
    )
    
    router = get_event_router()
    success = run_async(router.route_event(event))
    
    return jsonify({
        'event_id': event.id,
        'routed': success,
        'message': 'Device offline alert published'
    }), 201
    
# Build event shortcuts
@server_event_bp.route('/builds/deployed', methods=['POST'])
@handle_route_exceptions('event:emit_build_deployed')
def emit_build_deployed():
    """
    Emit build deployed event
    
    Body:
        - version: Build version (required)
        - userinterface: UI name (required)
        - environment: Environment (optional, default: staging)
    """
    data = request.get_json()
    
    if not data or 'version' not in data or 'userinterface' not in data:
        return jsonify({'error': 'version and userinterface required'}), 400
    
    team_id = data.get('team_id', get_team_id())
    
    event = Event(
        type="build.deployed",
        payload={
            "version": data['version'],
            "userinterface": data['userinterface'],
            "environment": data.get('environment', 'staging')
        },
        priority=EventPriority.HIGH,
        team_id=team_id
    )
    
    router = get_event_router()
    success = run_async(router.route_event(event))
    
    return jsonify({
        'event_id': event.id,
        'routed': success,
        'message': 'Build deployed event published'
    }), 201
    