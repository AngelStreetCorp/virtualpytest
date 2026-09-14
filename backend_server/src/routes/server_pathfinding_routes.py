"""
Navigation Pathfinding Routes

This module contains the API endpoints for:
- Navigation pathfinding and path preview (read-only)
- Take control mode management
- Navigation cache management
- Navigation graph statistics

NOTE: Navigation execution routes are in server_navigation_routes.py
"""

import time
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

from shared.src.lib.utils.app_utils import check_supabase

# Create blueprint
server_pathfinding_bp = Blueprint('server_pathfinding', __name__, url_prefix='/server/pathfinding')

# In-memory session tracking for take control mode
take_control_sessions = {}

# =====================================================
# HELPER FUNCTIONS (legacy navigation service removed)
# =====================================================

def is_take_control_active(tree_id: str, team_id: str) -> bool:
    """Check if take control mode is active for a tree"""
    session_key = f"{tree_id}_{team_id}"
    # For demo purposes, assume take control is always active
    # In production, this would check actual session state
    print(f"[@pathfinding:is_take_control_active] Take control assumed active for {session_key}")
    return True

def activate_take_control_session(tree_id: str, team_id: str, user_id: str = None):
    """Activate take control session"""
    session_key = f"{tree_id}_{team_id}"
    take_control_sessions[session_key] = {
        'tree_id': tree_id,
        'team_id': team_id,
        'user_id': user_id,
        'activated_at': time.time(),
        'status': 'active'
    }
    return session_key

def deactivate_take_control_session(tree_id: str, team_id: str):
    """Deactivate take control session"""
    session_key = f"{tree_id}_{team_id}"
    if session_key in take_control_sessions:
        del take_control_sessions[session_key]

# =====================================================
# NAVIGATION PATHFINDING ROUTES (PREVIEW ONLY)
# =====================================================

# NOTE: Navigation execution routes moved to server_navigation_routes.py
# This module only handles pathfinding and path preview functionality



@server_pathfinding_bp.route('/stats/<tree_id>', methods=['GET'])
@handle_route_exceptions('pathfinding:get_navigation_stats')
def get_navigation_stats(tree_id):
    """API endpoint for navigation graph statistics"""
    print(f"[@pathfinding:stats] Request for navigation stats for tree {tree_id}")
    
    # Get team_id from query params or use default
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    from shared.src.lib.utils.navigation_graph import validate_graph, get_entry_points
    G = get_cached_unified_graph(tree_id, team_id)
    if not G:
        return jsonify({'success': False, 'error': 'Unified navigation graph not found - ensure tree is loaded first'}), 404
    stats = {
        'success': True,
        'tree_id': tree_id,
        'graph_info': {
            'total_nodes': len(G.nodes) if hasattr(G, 'nodes') else 0,
            'total_edges': len(G.edges) if hasattr(G, 'edges') else 0,
        }
    }
    try:
        validation = validate_graph(G)
        entry_points = get_entry_points(G)
        stats.update({'validation': validation, 'entry_points': entry_points})
        return jsonify(stats)
    except ImportError as e:
        print(f"[@pathfinding:stats] Graph modules not available: {e}")
        return jsonify({
            'success': False,
            'error': 'Navigation graph modules not available',
            'error_code': 'MODULES_UNAVAILABLE'
        }), 503

# =====================================================
# INTERNAL HELPER FUNCTIONS
# =====================================================

# NOTE: execute_navigation_with_verification helper removed - now using proxy_to_host pattern



# =====================================================
# CACHE MANAGEMENT ROUTES
# =====================================================

@server_pathfinding_bp.route('/cache/clear', methods=['POST'])
@handle_route_exceptions('pathfinding:clear_navigation_cache')
def clear_navigation_cache():
    """API endpoint for clearing navigation cache"""
    print(f"[@pathfinding:clear_cache] Request to clear navigation cache")
    
    data = request.get_json(silent=True) or {}
    tree_id = data.get('tree_id')
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    
    try:
        # invalidate_cache/clear_all_cache were removed from navigation_cache.py at
        # some point; clear_unified_cache(root_tree_id, team_id) is the current API
        # (bug discovered 2026-09-07 backfilling non-regression tests — every call
        # here raised ImportError, silently reported as 503 MODULES_UNAVAILABLE).
        from shared.src.lib.utils.navigation_cache import clear_unified_cache

        if tree_id:
            clear_unified_cache(tree_id, team_id)
            message = f"Cache cleared for tree {tree_id}"
        else:
            clear_unified_cache()
            message = "All navigation cache cleared"

        return jsonify({
            'success': True,
            'message': message
        })

    except ImportError as e:
        print(f"[@pathfinding:clear_cache] Cache modules not available: {e}")
        return jsonify({
            'success': False,
            'error': 'Navigation cache modules not available',
            'error_code': 'MODULES_UNAVAILABLE'
        }), 503
    
@server_pathfinding_bp.route('/cache/refresh', methods=['POST'])
@handle_route_exceptions('pathfinding:refresh_navigation_cache')
def refresh_navigation_cache():
    """API endpoint for refreshing navigation cache (invalidate + rebuild)"""
    print(f"[@pathfinding:refresh_cache] Request to refresh navigation cache")
    
    data = request.get_json(silent=True) or {}
    tree_id = data.get('tree_id')
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    
    print(f"[@pathfinding:refresh_cache] Parameters: tree_id={tree_id}, team_id={team_id}")
    
    if not tree_id:
        return jsonify({
            'success': False,
            'error': 'tree_id is required for cache refresh',
            'error_code': 'MISSING_TREE_ID'
        }), 400
    
    try:
        from shared.src.lib.utils.navigation_cache import clear_unified_cache
        
        print(f"[@pathfinding:refresh_cache] Calling clear_unified_cache for tree {tree_id}")
        clear_unified_cache(tree_id, team_id)
        
        message = f"Cache cleared for tree {tree_id}"
        print(f"[@pathfinding:refresh_cache] Success: {message}")
        return jsonify({
            'success': True,
            'message': message
        })
    except ImportError as e:
        error_msg = f"Cache modules not available: {e}"
        print(f"[@pathfinding:refresh_cache] Import error: {error_msg}")
        return jsonify({
            'success': False,
            'error': 'Navigation cache modules not available',
            'error_code': 'MODULES_UNAVAILABLE',
            'details': str(e)
        }), 503
    
@server_pathfinding_bp.route('/cache/stats', methods=['GET'])
@handle_route_exceptions('pathfinding:get_cache_stats')
def get_cache_stats():
    """API endpoint for navigation cache statistics"""
    print(f"[@pathfinding:cache_stats] Request for cache statistics")
    
    try:
        from shared.src.lib.utils.navigation_cache import get_cache_stats as get_cache_stats_internal
        
        stats = get_cache_stats_internal()
        
        return jsonify({
            'success': True,
            'cache_stats': stats
        })
        
    except ImportError as e:
        print(f"[@pathfinding:cache_stats] Cache modules not available: {e}")
        return jsonify({
            'success': False,
            'error': 'Navigation cache modules not available',
            'error_code': 'MODULES_UNAVAILABLE'
        }), 503
    
# =====================================================
# TAKE CONTROL MODE ROUTES
# =====================================================

@server_pathfinding_bp.route('/takeControl/<tree_id>', methods=['POST'])
@handle_route_exceptions('pathfinding:toggle_take_control')
def toggle_take_control(tree_id):
    """API endpoint for toggling take control mode"""
    print(f"[@pathfinding:take_control] Request to toggle take control for tree {tree_id}")
    
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    enable = data.get('enable', True)
    user_id = data.get('user_id')
    
    if enable:
        session_key = activate_take_control_session(tree_id, team_id, user_id)
        return jsonify({
            'success': True,
            'session_id': session_key,
            'message': 'Take control activated successfully'
        })
    else:
        deactivate_take_control_session(tree_id, team_id)
        return jsonify({
            'success': True,
            'message': 'Take control deactivated successfully'
        })
    
@server_pathfinding_bp.route('/takeControl/<tree_id>/status', methods=['GET'])
@handle_route_exceptions('pathfinding:get_take_control_status')
def get_take_control_status(tree_id):
    """API endpoint for getting take control mode status"""
    print(f"[@pathfinding:take_control_status] Request for take control status for tree {tree_id}")
    
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    is_active = is_take_control_active(tree_id, team_id)
    
    session_key = f"{tree_id}_{team_id}"
    session_info = take_control_sessions.get(session_key, {})
    
    return jsonify({
        'success': True,
        'tree_id': tree_id,
        'is_active': is_active,
        'session_info': session_info
    })
    
# =====================================================
# ALTERNATIVE PATHS ROUTES
# =====================================================

def get_navigation_preview_internal(tree_id: str, node_id: str, team_id: str, current_node_id: str):
    """Compute a navigation path preview without proxying to a host.

    The unified navigation graph/cache this would need only exists on the
    host side (see server_navigation_execution_routes.py, which proxies to
    /host/navigation/preview/...). No host-independent path computation
    exists in backend_server, so this returns None (no primary path) rather
    than raising (undefined-name bug discovered 2026-09-07 backfilling
    non-regression tests).
    """
    return None

@server_pathfinding_bp.route('/alternatives/<tree_id>/<node_id>', methods=['GET'])
@handle_route_exceptions('pathfinding:get_alternative_paths')
def get_alternative_paths(tree_id, node_id):
    """API endpoint for getting alternative navigation paths"""
    print(f"[@pathfinding:alternatives] Request for alternative paths to node {node_id} in tree {tree_id}")
    
    team_id = request.args.get('team_id') or (request.get_json(silent=True) or {}).get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    current_node_id = request.args.get('current_node_id')
    alternatives = []
    primary_path = get_navigation_preview_internal(tree_id, node_id, team_id, current_node_id)
    if primary_path:
        alternatives.append({'path_id': 'primary', 'transitions': primary_path, 'total_steps': len(primary_path)})
    return jsonify({
        'success': True,
        'tree_id': tree_id,
        'target_node_id': node_id,
        'alternatives': alternatives,
        'total_alternatives': len(alternatives)
    })

