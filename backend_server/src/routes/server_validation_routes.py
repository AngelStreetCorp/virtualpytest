"""
Validation Routes - Reuses NavigationExecutor API for sequential edge testing
"""

from typing import List
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions


# Create blueprint
server_validation_bp = Blueprint('server_validation', __name__, url_prefix='/server/validation')

@server_validation_bp.route('/preview/<tree_id>', methods=['GET'])
@handle_route_exceptions('validation:get_validation_preview')
def get_validation_preview(tree_id: str):
    """
    Get validation preview - shows which edges will be validated using optimal depth-first sequence
    Uses unified cache system - requires proper cache population
    """
    team_id = request.args.get('team_id')
    host_name = request.args.get('host_name')
    
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
        
    if not host_name:
        return jsonify({
            'success': False,
            'message': 'host_name is required'
        }), 400
    
    # Use the same cache population pattern as navigation execution
    from backend_server.src.routes.server_control_routes import populate_navigation_cache_for_control
    
    print(f"[@route:get_validation_preview] Ensuring cache for tree {tree_id} on host {host_name}")
    cache_populated = populate_navigation_cache_for_control(tree_id, team_id, host_name)
    
    if not cache_populated:
        return jsonify({
            'success': False,
            'error': 'Failed to populate unified navigation cache. Tree may need to be loaded first.'
        }), 400
    
    # Use optimal edge validation sequence with unified cache
    from  backend_server.src.lib.utils.route_utils import proxy_to_host_direct
    from  backend_server.src.lib.utils.server_utils import get_host_manager
    
    # Get host info
    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if not host_info:
        return jsonify({
            'success': False,
            'error': f'Host {host_name} not found'
        }), 404
    
    proxy_result, _ = proxy_to_host_direct(
        host_info,
        '/host/navigation/validation_sequence', 
        'POST', 
        {
            'tree_id': tree_id,
            'team_id': team_id
        }
    )
    validation_sequence = proxy_result.get('sequence') if proxy_result and proxy_result.get('success') else None
    
    if not validation_sequence:
        return jsonify({
            'success': False,
            'error': 'No validation sequence found - tree may be empty or have no traversable edges'
        }), 400
    
    # Convert validation sequence to preview format - include cross-tree navigation details
    edges = []
    step_counter = 1

    for validation_step in validation_sequence:
        # Every row maps 1:1 to a real edge the runner will execute. Forced
        # repositioning hops have been removed from the validation sequence —
        # the runner repositions per-step at execution time.
        edge_info = {
            'step_number': step_counter,
            'from_node': validation_step['from_node_id'],
            'to_node': validation_step['to_node_id'],
            'from_name': validation_step['from_node_label'],
            'to_name': validation_step['to_node_label'],
            'selected': True,
            'actions': validation_step.get('actions', []),
            'has_verifications': validation_step.get('total_verifications', 0) > 0,
            'step_type': validation_step.get('step_type', 'unknown'),
            'transition_type': validation_step.get('transition_type', 'NORMAL'),
            'is_cross_tree': validation_step.get('tree_context_change', False),
            # Per-edge owning tree (destination tree of the transition).
            # Falls back to the requested tree_id when missing so the frontend
            # can always render a tree badge.
            'tree_id': validation_step.get('to_tree_id') or tree_id,
        }
        edges.append(edge_info)
        step_counter += 1

    print(f"[@route:get_validation_preview] Built {len(edges)} preview rows from {len(validation_sequence)} validation steps")

    # Resolve display names for every tree referenced by the preview so the
    # frontend can render a tree badge / build a tree filter without a
    # second round-trip per row.
    from shared.src.lib.database.navigation_trees_db import get_tree_metadata
    referenced_tree_ids = {edge['tree_id'] for edge in edges if edge.get('tree_id')}
    referenced_tree_ids.add(tree_id)
    trees = {}
    for tid in referenced_tree_ids:
        meta = get_tree_metadata(tid, team_id)
        if meta.get('success'):
            tree_row = meta['tree']
            trees[tid] = {
                'id': tid,
                'name': tree_row.get('name') or tid,
                'is_root': bool(tree_row.get('is_root_tree')),
            }
        else:
            trees[tid] = {'id': tid, 'name': tid, 'is_root': tid == tree_id}

    return jsonify({
        'success': True,
        'tree_id': tree_id,
        'total_edges': len(edges),
        'edges': edges,
        'trees': trees,
        'algorithm': 'unified_depth_first_traversal'
    })
    
# Removed legacy cache population functions - now using populate_navigation_cache_for_control

# Removed /status/<task_id> route - no longer needed since validation uses useScript directly

# Removed /run/<tree_id> route - validation now uses existing useScript infrastructure
# The frontend calls the validation script directly through RunTests.tsx + useScript.ts
