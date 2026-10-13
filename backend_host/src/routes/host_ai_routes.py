"""
Host AI Routes - Device AI Execution

Graph generation from a prompt (the device's AIGraphBuilder), or, with `current_graph`,
a prompt edit of an open step-list graph. Running the graph is the
testcase executor's job (/host/testcase/execute, /host/testcase/execute-from-prompt).
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler

# Create blueprint
host_ai_bp = Blueprint('host_ai', __name__, url_prefix='/host/ai')

@host_ai_bp.route('/generatePlan', methods=['POST'])
@route_exception_handler()
def ai_generate_plan():
    print("[@host_ai] Starting AI graph generation")
    
    # Get request data
    data = request.get_json() or {}
    prompt = data.get('prompt', '')
    device_id = data.get('device_id', 'device1')
    userinterface_name = data.get('userinterface_name', 'example_mobile')
    current_node_id = data.get('current_node_id')
    available_nodes = data.get('available_nodes')  # NEW: Accept from caller
    team_id = request.args.get('team_id')
    
    print(f"[@host_ai] Generating graph for device: {device_id}, team: {team_id}")
    print(f"[@host_ai] Prompt: {prompt[:100]}...")
    
    # Validate
    if not prompt:
        return jsonify({
            'success': False,
            'error': 'Prompt is required'
        }), 400
    
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
    
    # Get device from app registry
    if not hasattr(current_app, 'host_devices') or device_id not in current_app.host_devices:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} not found in host registry'
        }), 404
    
    device = current_app.host_devices[device_id]
    
    print(f"[@host_ai] Using AI service for device: {device_id}")
    
    # Check if device has ai_builder
    if not hasattr(device, 'ai_builder') or not device.ai_builder:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have AIGraphBuilder initialized'
        }), 500
    
    # Prompt editing: change the open step-list graph instead of generating a new one
    current_graph = data.get('current_graph')
    if current_graph is not None:
        return jsonify(device.ai_builder.edit_graph(
            prompt=prompt,
            current_graph=current_graph,
            userinterface_name=userinterface_name,
            team_id=team_id,
        ))

    # Generate graph using AIGraphBuilder
    result = device.ai_builder.generate_graph(
        prompt=prompt,
        userinterface_name=userinterface_name,
        team_id=team_id,
        current_node_id=current_node_id,
        available_nodes=available_nodes  # NEW: Pass to AI builder
    )
    
    print(f"[@host_ai] Graph generation result: success={result.get('success')}")
    print(f"[@host_ai] Result keys: {list(result.keys())}")
    print(f"[@host_ai] needs_disambiguation: {result.get('needs_disambiguation')}")
    
    if result.get('needs_disambiguation'):
        print(f"[@host_ai] ⚠️  DISAMBIGUATION - ambiguities count: {len(result.get('ambiguities', []))}")
    
    return jsonify(result)
