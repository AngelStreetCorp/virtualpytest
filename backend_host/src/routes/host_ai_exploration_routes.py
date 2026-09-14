"""
Host AI Exploration Routes - Thin HTTP layer for AI-driven tree exploration

Architecture:
- Thin routes that delegate to device.exploration_executor
- No business logic in routes
- No global session dict (state is device-bound)
- Consistent with host_*_routes.py naming convention
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from shared.src.lib.database.navigation_trees_db import (
    get_tree_nodes,
    get_tree_edges,
    batch_delete_edges_except,
    batch_delete_nodes_except,
    save_nodes_batch,
    save_edges_batch
)

host_ai_exploration_bp = Blueprint('host_ai_exploration', __name__, url_prefix='/host/ai-generation')


@host_ai_exploration_bp.route('/cleanup-temp', methods=['POST'])
@route_exception_handler()
def cleanup_temp():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    tree_id = data.get('tree_id')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    if not tree_id:
        return jsonify({'success': False, 'error': 'tree_id required'}), 400
    
    print(f"[@route:ai_generation:cleanup_temp] Cleaning up _temp for tree: {tree_id}")
    
    # ✅ BATCH DELETE: Delete ALL edges except entry-to-home in ONE query
    # Find entry-to-home edge ID
    edges_result = get_tree_edges(tree_id, team_id)
    entry_edge_id = None
    
    if edges_result.get('success') and edges_result.get('edges'):
        for edge in edges_result['edges']:
            if 'entry' in edge.get('edge_id', '').lower() and edge.get('target_node_id', '').lower() == 'home':
                entry_edge_id = edge['edge_id']
                break
    
    # Batch delete all edges except entry-to-home
    keep_edges = [entry_edge_id] if entry_edge_id else []
    edges_delete_result = batch_delete_edges_except(tree_id, team_id, keep_edges)
    edges_deleted = edges_delete_result.get('deleted_count', 0)
    
    print(f"[@route:ai_generation:cleanup_temp] ✅ Batch deleted {edges_deleted} edges (kept: {keep_edges})")
    
    # Batch delete all nodes except entry-node, home, and subtree root (if exists)
    keep_nodes = ['entry-node', 'home']
    
    # ✅ SUBTREE PROTECTION: Check if this is a subtree and preserve the parent reference node
    nodes_result = get_tree_nodes(tree_id, team_id)
    if nodes_result.get('success') and nodes_result.get('nodes'):
        for node in nodes_result['nodes']:
            node_data = node.get('data', {})
            if node_data.get('isParentReference') is True:
                subtree_root_id = node.get('node_id')
                keep_nodes.append(subtree_root_id)
                print(f"[@route:ai_generation:cleanup_temp] 🌲 Detected subtree - protecting root node: {subtree_root_id}")
                break
    
    nodes_delete_result = batch_delete_nodes_except(tree_id, team_id, keep_nodes)
    nodes_deleted = nodes_delete_result.get('deleted_count', 0)
    
    print(f"[@route:ai_generation:cleanup_temp] ✅ Batch deleted {nodes_deleted} nodes (kept: {keep_nodes})")
    print(f"[@route:ai_generation:cleanup_temp] Complete: {nodes_deleted} nodes, {edges_deleted} edges deleted")
    
    # ✅ Clear and REBUILD cache after cleanup (don't wait for next take-control)
    # This ensures start-exploration works immediately after cleanup
    from shared.src.lib.database.navigation_trees_db import invalidate_navigation_cache_for_tree, get_complete_tree_hierarchy
    from shared.src.lib.utils.navigation_cache import populate_unified_cache
    
    # 1. Clear old cache
    invalidate_navigation_cache_for_tree(tree_id, team_id)
    print(f"[@route:ai_generation:cleanup_temp] ✅ Cache invalidated for tree {tree_id}")
    
    # 2. Rebuild cache immediately
    hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
    if hierarchy_result and hierarchy_result.get('all_trees_data'):
        unified_graph = populate_unified_cache(tree_id, team_id, hierarchy_result['all_trees_data'])
        if unified_graph:
            print(f"[@route:ai_generation:cleanup_temp] ✅ Cache rebuilt: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")
            
            # 3. Update all NavigationExecutor instances
            from flask import current_app
            host_devices = getattr(current_app, 'host_devices', {})
            for device_id, device in host_devices.items():
                if hasattr(device, 'navigation_executor') and device.navigation_executor:
                    device.navigation_executor.unified_graph = unified_graph
                    print(f"[@route:ai_generation:cleanup_temp] Updated NavigationExecutor for device {device_id}")
        else:
            print(f"[@route:ai_generation:cleanup_temp] ⚠️ Failed to rebuild cache (empty graph)")
    else:
        print(f"[@route:ai_generation:cleanup_temp] ⚠️ No hierarchy data to rebuild cache")
    
    return jsonify({
        'success': True,
        'nodes_deleted': nodes_deleted,
        'edges_deleted': edges_deleted
    })
    
@host_ai_exploration_bp.route('/start-exploration', methods=['POST'])
@route_exception_handler()
def start_exploration():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    
    # Validate params
    tree_id = data.get('tree_id')
    root_tree_id = data.get('root_tree_id', tree_id)  # ✅ NEW: Root tree for pathfinding (defaults to tree_id)
    device_id = data.get('device_id', 'device1')
    userinterface_name = data.get('userinterface_name')
    original_prompt = data.get('original_prompt', '')
    start_node = data.get('start_node', 'home')  # NEW: Defaults to 'home'
    
    # 🔍 DEBUG LOG: Show what's being started
    print(f"[@route:ai_generation:start_exploration] Starting exploration:")
    print(f"  tree_id: {tree_id}")
    print(f"  root_tree_id: {root_tree_id}")
    print(f"  device_id: {device_id}")
    print(f"  userinterface_name: {userinterface_name}")
    print(f"  start_node: {start_node}")
    print(f"  available devices: {list(current_app.host_devices.keys())}")
    
    if not team_id:
        print(f"[@route:ai_generation:start_exploration] ❌ Missing team_id")
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    if not tree_id:
        print(f"[@route:ai_generation:start_exploration] ❌ Missing tree_id")
        return jsonify({'success': False, 'error': 'tree_id required'}), 400
    if not userinterface_name:
        print(f"[@route:ai_generation:start_exploration] ❌ Missing userinterface_name")
        return jsonify({'success': False, 'error': 'userinterface_name required'}), 400
    
    # Get device
    if device_id not in current_app.host_devices:
        print(f"[@route:ai_generation:start_exploration] ❌ Device '{device_id}' not found")
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    print(f"[@route:ai_generation:start_exploration] ✅ Starting exploration on device '{device_id}'")
    
    # Delegate to exploration executor
    result = device.exploration_executor.start_exploration(
        tree_id=tree_id,
        root_tree_id=root_tree_id,  # ✅ NEW: Pass root tree for pathfinding
        userinterface_name=userinterface_name,
        team_id=team_id,
        original_prompt=original_prompt,
        start_node=start_node  # NEW: Pass start_node
    )
    
    print(f"[@route:ai_generation:start_exploration] Result: success={result.get('success', False)}, exploration_id={result.get('exploration_id', 'N/A')}")
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/init', methods=['POST'])
@route_exception_handler()
def init_exploration():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.execute_phase0()
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/next', methods=['POST'])
@route_exception_handler()
def next_item():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.execute_phase2_next_item()
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/exploration-status/<exploration_id>', methods=['GET'])
@route_exception_handler()
def exploration_status(exploration_id):
    # Get device_id from query params (frontend should send this)
    device_id_requested = request.args.get('device_id')
    device_id = device_id_requested or 'device1'
    
    # 🔍 DEBUG LOG: Show what's being checked
    print(f"[@route:ai_generation:exploration_status] Checking exploration status:")
    print(f"  exploration_id: {exploration_id}")
    print(f"  device_id requested: {device_id_requested}")
    print(f"  device_id used: {device_id}")
    print(f"  available devices: {list(current_app.host_devices.keys())}")
    
    if device_id not in current_app.host_devices:
        print(f"[@route:ai_generation:exploration_status] ❌ Device '{device_id}' not found")
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # 🔍 DEBUG LOG: Show if device has active exploration
    has_exploration = device.exploration_executor.current_exploration_id is not None
    print(f"[@route:ai_generation:exploration_status] Device '{device_id}' has active exploration: {has_exploration}")
    if has_exploration:
        print(f"  Active exploration ID: {device.exploration_executor.current_exploration_id}")
    
    # Delegate to exploration executor
    result = device.exploration_executor.get_exploration_status()
    
    # 🔍 DEBUG LOG: Show result
    print(f"[@route:ai_generation:exploration_status] Result: {result.get('status', 'unknown')} (success={result.get('success', False)})")
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/continue-exploration', methods=['POST'])
@route_exception_handler()
def continue_exploration():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    device_id = data.get('device_id', 'device1')
    selected_items = data.get('selected_items')  # ✅ Get user selection
    cleaned_lines = data.get('cleaned_lines')  # ✅ User-edited lines (AI corrections)
    cleaned_duplicate_positions = data.get('cleaned_duplicate_positions')  # ✅ Recalculated duplicates
    
    print(f"[@route:ai_generation:continue_exploration] Received selected_items: {selected_items}")
    print(f"[@route:ai_generation:continue_exploration] Type: {type(selected_items)}, Length: {len(selected_items) if selected_items else 0}")
    if cleaned_lines:
        print(f"[@route:ai_generation:continue_exploration] ✏️ User edited plan - using cleaned data")
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor with selected items and cleaned data
    result = device.exploration_executor.continue_exploration(
        team_id=team_id,
        selected_items=selected_items,
        cleaned_lines=cleaned_lines,
        cleaned_duplicate_positions=cleaned_duplicate_positions
    )
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/start-validation', methods=['POST'])
@route_exception_handler()
def start_validation():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.start_validation()
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/validate-next-item', methods=['POST'])
@route_exception_handler()
def validate_next_item():
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.validate_next_item()
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/start-node-verification', methods=['POST'])
@route_exception_handler()
def start_node_verification():
    print(f"[@route:ai_generation:start_node_verification] START")
    data = request.get_json() or {}
    device_id = data.get('device_id', 'device1')
    
    print(f"[@route:ai_generation:start_node_verification] device_id: {device_id}")
    print(f"[@route:ai_generation:start_node_verification] Available devices: {list(current_app.host_devices.keys())}")
    
    if device_id not in current_app.host_devices:
        print(f"[@route:ai_generation:start_node_verification] Device {device_id} not found!")
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    print(f"[@route:ai_generation:start_node_verification] Calling device.exploration_executor.start_node_verification()")
    result = device.exploration_executor.start_node_verification()
    
    print(f"[@route:ai_generation:start_node_verification] Result: {result}")
    return jsonify(result)
    
@host_ai_exploration_bp.route('/approve-node-verifications', methods=['POST'])
@route_exception_handler()
def approve_node_verifications():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    device_id = data.get('device_id', 'device1')
    approved_verifications = data.get('approved_verifications', [])
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    result = device.exploration_executor.approve_node_verifications(
        approved_verifications=approved_verifications,
        team_id=team_id
    )
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/finalize-structure', methods=['POST'])
@route_exception_handler()
def finalize_structure():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    tree_id = data.get('tree_id')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    if not tree_id:
        return jsonify({'success': False, 'error': 'tree_id required'}), 400
    
    print(f"[@route:ai_generation:finalize_structure] Removing _temp from labels for tree: {tree_id}")
    
    # Get all nodes and edges from tree
    from shared.src.lib.database.navigation_trees_db import (
        get_tree_nodes, 
        get_tree_edges,
        get_supabase
    )
    
    nodes_result = get_tree_nodes(tree_id, team_id)
    edges_result = get_tree_edges(tree_id, team_id)
    
    if not nodes_result.get('success') or not edges_result.get('success'):
        return jsonify({'success': False, 'error': 'Failed to get tree data'}), 400
    
    nodes = nodes_result.get('nodes', [])
    edges = edges_result.get('edges', [])
    
    nodes_updated = 0
    edges_updated = 0
    
    # Prepare Batch Updates
    nodes_to_update = []
    edges_to_update = []

    # Update node labels: remove _temp suffix
    for node in nodes:
        label = node.get('label', '')
        if label.endswith('_temp'):
            new_label = label.replace('_temp', '')
            node['label'] = new_label
            nodes_to_update.append(node)
            print(f"  Queueing node label update: {label} → {new_label}")

    # Update edge labels: remove _temp suffix
    for edge in edges:
        label = edge.get('label', '')
        if label and '_temp' in label:
            new_label = label.replace('_temp', '')
            edge['label'] = new_label
            edges_to_update.append(edge)
            print(f"  Queueing edge label update: {label} → {new_label}")
    
    # Execute Batch Updates
    if nodes_to_update:
        print(f"[@route:ai_generation:finalize_structure] Batch updating {len(nodes_to_update)} nodes...")
        res = save_nodes_batch(tree_id, nodes_to_update, team_id)
        if res['success']:
            nodes_updated = len(nodes_to_update)
            print(f"  ✅ Successfully updated {nodes_updated} nodes")
        else:
            print(f"  ❌ Failed to update nodes: {res.get('error')}")
            return jsonify({'success': False, 'error': f"Node update failed: {res.get('error')}"}), 500

    if edges_to_update:
        print(f"[@route:ai_generation:finalize_structure] Batch updating {len(edges_to_update)} edges...")
        res = save_edges_batch(tree_id, edges_to_update, team_id)
        if res['success']:
            edges_updated = len(edges_to_update)
            print(f"  ✅ Successfully updated {edges_updated} edges")
        else:
            print(f"  ❌ Failed to update edges: {res.get('error')}")
            return jsonify({'success': False, 'error': f"Edge update failed: {res.get('error')}"}), 500
    
    # ✅ Clear and REBUILD cache after finalize (don't wait for next take-control)
    # This ensures user can navigate immediately after AI generation completes
    from shared.src.lib.database.navigation_trees_db import invalidate_navigation_cache_for_tree, get_complete_tree_hierarchy
    from shared.src.lib.utils.navigation_cache import populate_unified_cache
    
    # 1. Clear old cache
    invalidate_navigation_cache_for_tree(tree_id, team_id)
    print(f"[@route:ai_generation:finalize_structure] ✅ Cache invalidated for tree {tree_id}")
    
    # 2. Rebuild cache immediately
    hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
    if hierarchy_result and hierarchy_result.get('all_trees_data'):
        unified_graph = populate_unified_cache(tree_id, team_id, hierarchy_result['all_trees_data'])
        if unified_graph:
            print(f"[@route:ai_generation:finalize_structure] ✅ Cache rebuilt: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")
            
            # 3. Update all NavigationExecutor instances on this host
            from flask import current_app
            host_devices = getattr(current_app, 'host_devices', {})
            for device_id, device in host_devices.items():
                if hasattr(device, 'navigation_executor') and device.navigation_executor:
                    device.navigation_executor.unified_graph = unified_graph
                    print(f"[@route:ai_generation:finalize_structure] ✅ Updated NavigationExecutor for device {device_id}")
        else:
            print(f"[@route:ai_generation:finalize_structure] ⚠️ Failed to rebuild cache (empty graph)")
    else:
        print(f"[@route:ai_generation:finalize_structure] ⚠️ No hierarchy data to rebuild cache")
    
    print(f"[@route:ai_generation:finalize_structure] Complete: {nodes_updated} nodes, {edges_updated} edges updated")
    
    return jsonify({
        'success': True,
        'nodes_renamed': nodes_updated,  # Keep old key name for frontend compatibility
        'edges_renamed': edges_updated,  # Keep old key name for frontend compatibility
        'message': f'Finalized: {nodes_updated} node labels and {edges_updated} edge labels updated'
    })
        
@host_ai_exploration_bp.route('/approve-generation', methods=['POST'])
@route_exception_handler()
def approve_generation():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    device_id = data.get('device_id', 'device1')
    
    tree_id = data.get('tree_id')
    approved_nodes = data.get('approved_nodes', [])
    approved_edges = data.get('approved_edges', [])
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.approve_generation(
        tree_id=tree_id,
        approved_nodes=approved_nodes,
        approved_edges=approved_edges,
        team_id=team_id
    )
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/cancel-exploration', methods=['POST'])
@route_exception_handler()
def cancel_exploration():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    device_id = data.get('device_id', 'device1')
    
    tree_id = data.get('tree_id')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id required'}), 400
    
    # Get device
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    
    # Delegate to exploration executor
    result = device.exploration_executor.cancel_exploration(
        tree_id=tree_id,
        team_id=team_id
    )
    
    return jsonify(result)
    
@host_ai_exploration_bp.route('/auto-discover-screen', methods=['POST'])
@route_exception_handler()
def auto_discover_screen():
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    tree_id = data.get('tree_id')
    device_id = data.get('device_id', 'device1')
    userinterface_name = data.get('userinterface_name')
    parent_node_id = data.get('parent_node_id', 'home')
    
    if not all([team_id, tree_id, userinterface_name]):
        return jsonify({'success': False, 'error': 'team_id, tree_id and userinterface_name required'}), 400
    
    if device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    result = device.exploration_executor.auto_discover_screen(tree_id, team_id, userinterface_name, parent_node_id)
    
    return jsonify(result)
    
