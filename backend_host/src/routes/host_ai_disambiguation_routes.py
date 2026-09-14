"""
Host AI Disambiguation Routes

Routes for AI prompt pre-processing and disambiguation management.
Handles prompt analysis, saving user choices, and managing learned mappings.
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.services.ai.ai_preprocessing import preprocess_prompt
from shared.src.lib.database.ai_prompt_disambiguation_db import (
    save_disambiguation,
    get_all_disambiguations,
    delete_disambiguation,
    get_disambiguation_stats
)

# Create blueprint
host_ai_disambiguation_bp = Blueprint('host_ai_disambiguation', __name__, 
                                     url_prefix='/host/ai-disambiguation')


@host_ai_disambiguation_bp.route('/analyzePrompt', methods=['POST'])
@route_exception_handler()
def analyze_prompt():
    data = request.get_json()
    prompt = data.get('prompt')
    userinterface_name = data.get('userinterface_name')
    device_id = data.get('device_id', 'device1')
    team_id = data.get('team_id')
    
    # Validate required fields
    if not all([prompt, userinterface_name, team_id]):
        return jsonify({
            'success': False, 
            'error': 'Missing required fields: prompt, userinterface_name, team_id'
        }), 400
    
    print(f"[@host_ai_disambiguation:analyze_prompt] Analyzing prompt: '{prompt[:50]}...'")
    
    # Get device from app context
    host_devices = getattr(current_app, 'host_devices', {})
    device = host_devices.get(device_id)
    
    if not device:
        return jsonify({
            'success': False, 
            'error': f'Device {device_id} not found in host'
        }), 404
    
    # Get available nodes from navigation executor
    nav_context = device.navigation_executor.get_available_context(userinterface_name, team_id)
    available_nodes = nav_context.get('available_nodes', [])
    
    print(f"[@host_ai_disambiguation:analyze_prompt] Available nodes: {len(available_nodes)}")
    
    # Analyze prompt for ambiguities
    analysis = preprocess_prompt(prompt, available_nodes, team_id, userinterface_name)
    
    print(f"[@host_ai_disambiguation:analyze_prompt] Analysis status: {analysis.get('status')}")
    
    # Handle exact match - create direct navigation plan (skip AI)
    if analysis.get('status') == 'exact_match':
        target_node = analysis.get('target_node')
        print(f"[@host_ai_disambiguation:analyze_prompt] ✅ Exact match found: '{target_node}' - creating direct plan (AI not needed)")
        
        # Create direct navigation plan
        direct_plan = {
            'steps': [{
                'step_number': 1,
                'command': 'execute_navigation',
                'params': {
                    'target_node': target_node
                },
                'description': f"Navigate to {target_node}",
                'source': 'direct_match'
            }],
            'total_steps': 1,
            'estimated_duration': '5s',
            'source': 'preprocessing',
            'reason': 'exact_match_found'
        }
        
        return jsonify({
            'success': True,
            'analysis': analysis,
            'direct_plan': direct_plan,  # Include ready-to-execute plan
            'available_nodes': available_nodes
        })
    
    return jsonify({
        'success': True,
        'analysis': analysis,
        'available_nodes': available_nodes  # For manual edit mode in UI
    })
    
@host_ai_disambiguation_bp.route('/saveDisambiguation', methods=['POST'])
@route_exception_handler()
def save_disambiguation_route():
    data = request.get_json()
    team_id = data.get('team_id')
    userinterface_name = data.get('userinterface_name')
    selections = data.get('selections', [])
    
    # Validate required fields
    if not all([team_id, userinterface_name]):
        return jsonify({
            'success': False, 
            'error': 'Missing required fields: team_id, userinterface_name'
        }), 400
    
    if not selections:
        return jsonify({
            'success': False, 
            'error': 'No selections provided'
        }), 400
    
    print(f"[@host_ai_disambiguation:save] Saving {len(selections)} disambiguation(s)")
    
    # Save each selection
    saved_count = 0
    for selection in selections:
        phrase = selection.get('phrase')
        resolved = selection.get('resolved')
        
        if not phrase or not resolved:
            print(f"[@host_ai_disambiguation:save] Skipping invalid selection: {selection}")
            continue
        
        result = save_disambiguation(team_id, userinterface_name, phrase, resolved)
        
        if result.get('success'):
            saved_count += 1
            print(f"[@host_ai_disambiguation:save] Saved: '{phrase}' → '{resolved}'")
        else:
            print(f"[@host_ai_disambiguation:save] Failed to save: '{phrase}' → '{resolved}'")
    
    return jsonify({
        'success': True,
        'saved_count': saved_count,
        'message': f'Saved {saved_count} disambiguation choice(s)'
    })
    
@host_ai_disambiguation_bp.route('/getMappings', methods=['GET'])
@route_exception_handler()
def get_mappings():
    team_id = request.args.get('team_id')
    userinterface_name = request.args.get('userinterface_name')
    limit = int(request.args.get('limit', 100))
    
    # Validate required fields
    if not team_id:
        return jsonify({
            'success': False, 
            'error': 'Missing required query param: team_id'
        }), 400
    
    print(f"[@host_ai_disambiguation:get_mappings] Getting mappings for team {team_id}")
    
    # Get all disambiguations
    mappings = get_all_disambiguations(team_id, userinterface_name, limit)
    
    # Get stats
    stats = get_disambiguation_stats(team_id, userinterface_name)
    
    return jsonify({
        'success': True,
        'mappings': mappings,
        'stats': stats
    })
    
@host_ai_disambiguation_bp.route('/deleteMapping/<mapping_id>', methods=['DELETE'])
@route_exception_handler()
def delete_mapping_route(mapping_id):
    team_id = request.args.get('team_id')
    
    # Validate required fields
    if not team_id:
        return jsonify({
            'success': False, 
            'error': 'Missing required query param: team_id'
        }), 400
    
    print(f"[@host_ai_disambiguation:delete_mapping] Deleting mapping {mapping_id}")
    
    # Delete mapping
    success = delete_disambiguation(team_id, mapping_id)
    
    if success:
        return jsonify({
            'success': True,
            'message': 'Mapping deleted successfully'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Mapping not found or already deleted'
        }), 404
    
