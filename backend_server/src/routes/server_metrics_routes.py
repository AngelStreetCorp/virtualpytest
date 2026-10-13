"""
Navigation Metrics API Routes

This module implements the metrics API endpoints as specified in:
docs/architecture/navigation_metrics.md

Provides clean, architecture-compliant endpoints for:
- Tree metrics (aggregated node and edge metrics)
- Individual node metrics
- Individual edge metrics  
- Action execution history
- Verification execution history

No legacy code or backward compatibility - follows the clean embedded architecture.
"""

from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.tree_metrics_payload import build_tree_metrics_payload
from shared.src.lib.database.navigation_metrics_db import (
    get_tree_metrics,
    get_action_execution_history,
    get_verification_execution_history
)
from shared.src.lib.database.navigation_trees_db import get_tree_nodes, get_tree_edges
from shared.src.lib.utils.app_utils import check_supabase
from shared.src.lib.utils.navigation_graph import canonical_variant_name

# Create blueprint
server_metrics_bp = Blueprint('server_metrics', __name__, url_prefix='/server/metrics')

# =====================================================
# TREE METRICS ENDPOINTS
# =====================================================

@server_metrics_bp.route('/tree/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_tree_metrics_api')
def get_tree_metrics_api(tree_id):
    """
    Get aggregated metrics for all nodes and edges in a navigation tree.
    
    Query parameters:
        team_id: required
        variant: run scope (lowercase variant name); omitted = base runs only

    Returns metrics in the format expected by the frontend (useMetrics):
    {
        success: true,
        nodes: {node_id: {volume, success_rate, avg_verification_time, confidence}},
        edges: {edge_id#action_set_id: {volume, success_rate, avg_action_time,
                                        avg_kpi_ms, kpi_volume, kpi_report_url, confidence}}
    }
    """
    error = check_supabase()
    if error:
        return error

    team_id = request.args.get('team_id')
    variant = canonical_variant_name(request.args.get('variant'))

    print(f"[@route:metrics:get_tree_metrics] Fetching metrics for tree: {tree_id}, team: {team_id}, variant: {variant or 'base'}")
    
    # Get complete tree hierarchy (root + all nested subtrees)
    from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy
    
    hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
    if not hierarchy_result.get('success', False):
        return jsonify({
            'success': False,
            'error': f'Failed to fetch tree hierarchy: {hierarchy_result.get("error", "Unknown error")}'
        }), 400
    
    # Collect all nodes and edges from entire hierarchy
    all_nodes = []
    all_edges = []
    hierarchy_trees = []
    
    for tree_data in hierarchy_result.get('all_trees_data', []):
        tree_info = tree_data.get('tree_info', {})
        hierarchy_trees.append({
            'tree_id': tree_data['tree_id'],
            'name': tree_info.get('name', ''),
            'depth': tree_info.get('tree_depth', 0),
            'is_root': tree_info.get('is_root_tree', False)
        })
        
        # Add nodes and edges from this tree
        all_nodes.extend(tree_data.get('nodes', []))
        all_edges.extend(tree_data.get('edges', []))
    
    # Extract node and edge IDs from entire hierarchy
    node_ids = [node['node_id'] for node in all_nodes]
    edge_ids = [edge['edge_id'] for edge in all_edges]
    
    print(f"[@route:metrics:get_tree_metrics] Hierarchy: {len(hierarchy_trees)} trees, {len(node_ids)} nodes, {len(edge_ids)} edges")
    for tree_info in hierarchy_trees:
        print(f"[@route:metrics:get_tree_metrics] - Tree: {tree_info['name']} (depth: {tree_info['depth']}, root: {tree_info['is_root']})")
    
    payload = build_tree_metrics_payload(team_id, node_ids, edge_ids, variant)

    return jsonify({
        'success': True,
        **payload,
        'hierarchy_info': {
            'total_trees': len(hierarchy_trees),
            'max_depth': max([t['depth'] for t in hierarchy_trees]) if hierarchy_trees else 0,
            'has_nested_trees': len(hierarchy_trees) > 1,
            'trees': hierarchy_trees
        }
    })

# =====================================================
# INDIVIDUAL METRICS ENDPOINTS
# =====================================================

@server_metrics_bp.route('/node/<node_id>/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_node_metrics_api')
def get_node_metrics_api(node_id, tree_id):
    """Get metrics for a specific node."""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    variant = canonical_variant_name(request.args.get('variant'))

    print(f"[@route:metrics:get_node_metrics] Fetching metrics for node: {node_id}, tree: {tree_id}")

    # Get metrics for single node
    metrics = get_tree_metrics(team_id, [node_id], [], variant)
    node_metric = metrics['nodes'].get(node_id)
    
    return jsonify({
        'success': True,
        'node_metric': node_metric
    })
    
@server_metrics_bp.route('/edge/<edge_id>/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_edge_metrics_api')
def get_edge_metrics_api(edge_id, tree_id):
    """Get metrics for a specific edge (all directions)."""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    variant = canonical_variant_name(request.args.get('variant'))

    print(f"[@route:metrics:get_edge_metrics] Fetching metrics for edge: {edge_id}, tree: {tree_id}")

    # Get metrics for single edge - now returns direction-specific metrics
    metrics = get_tree_metrics(team_id, [], [edge_id], variant)
    
    # Return all direction-specific metrics for this edge
    edge_metrics = {}
    for key, metric_data in metrics['edges'].items():
        if key.startswith(edge_id):
            edge_metrics[key] = metric_data
    
    return jsonify({
        'success': True,
        'edge_metrics': edge_metrics  # Changed from edge_metric to edge_metrics
    })
    
@server_metrics_bp.route('/edge/<edge_id>/<action_set_id>/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_edge_direction_metrics_api')
def get_edge_direction_metrics_api(edge_id, action_set_id, tree_id):
    """Get metrics for a specific edge direction (edge_id + action_set_id)."""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    variant = canonical_variant_name(request.args.get('variant'))

    from shared.src.lib.database.navigation_metrics_db import get_edge_direction_metrics

    print(f"[@route:metrics:get_edge_direction_metrics] Fetching metrics for edge: {edge_id}, action_set: {action_set_id}, tree: {tree_id}")

    metrics = get_edge_direction_metrics(team_id, edge_id, action_set_id, variant)
    
    return jsonify({
        'success': True,
        'metrics': metrics
    })
    
# =====================================================
# EXECUTION HISTORY ENDPOINTS
# =====================================================

@server_metrics_bp.route('/history/actions/<edge_id>/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_action_history_api')
def get_action_history_api(edge_id, tree_id):
    """Get execution history for actions in an edge."""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    limit = request.args.get('limit', 100, type=int)
    
    print(f"[@route:metrics:get_action_history] Fetching history for edge: {edge_id}, tree: {tree_id}")
    
    history_result = get_action_execution_history(team_id, edge_id, tree_id, limit)
    
    return jsonify(history_result)
    
@server_metrics_bp.route('/history/verifications/<node_id>/<tree_id>', methods=['GET'])
@handle_route_exceptions('metrics:get_verification_history_api')
def get_verification_history_api(node_id, tree_id):
    """Get execution history for verifications in a node."""
    error = check_supabase()
    if error:
        return error
        
    team_id = request.args.get('team_id')
    
    limit = request.args.get('limit', 100, type=int)
    
    print(f"[@route:metrics:get_verification_history] Fetching history for node: {node_id}, tree: {tree_id}")
    
    history_result = get_verification_execution_history(team_id, node_id, tree_id, limit)
    
    return jsonify(history_result)
    