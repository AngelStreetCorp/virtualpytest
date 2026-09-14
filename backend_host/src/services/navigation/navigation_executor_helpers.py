"""
Navigation Executor Helper Functions

Pure utility functions extracted from NavigationExecutor for better maintainability.
These functions have no state dependencies and can be used independently.
"""

from typing import Dict, List, Optional


def find_node_by_label(nodes: List[Dict], label: str) -> Optional[Dict]:
    """
    Find node by its label in a generic way.
    
    Args:
        nodes: List of node dictionaries
        label: Node label to search for
        
    Returns:
        Node dictionary with the matching label, or None if not found
    """
    for node in nodes:
        if node.get('label') == label:
            return node
    return None


def find_edges_from_node(source_node_id: str, edges: List[Dict]) -> List[Dict]:
    """
    Find all edges originating from a specific node (generic version).
    
    Args:
        source_node_id: Source node ID
        edges: List of edge dictionaries
        
    Returns:
        List of edges originating from the specified node
    """
    return [edge for edge in edges if edge.get('source_node_id') == source_node_id]


def find_edge_by_target_label(source_node_id: str, edges: List[Dict], nodes: List[Dict], target_label: str) -> Optional[Dict]:
    """
    Find edge from source node to a target node with specific label.
    This is the proper generic way to find action edges.
    
    Args:
        source_node_id: Source node ID
        edges: List of edge dictionaries
        nodes: List of node dictionaries  
        target_label: Label of target node to find
        
    Returns:
        Edge dictionary going to target node with specified label, or None if not found
    """
    # First find the target node by label
    target_node = find_node_by_label(nodes, target_label)
    if not target_node:
        return None
    
    target_node_id = target_node.get('node_id')
    if not target_node_id:
        return None
    
    # Find edge from source to target
    source_edges = find_edges_from_node(source_node_id, edges)
    for edge in source_edges:
        if edge.get('target_node_id') == target_node_id:
            return edge
    
    return None


def find_edge_with_action_command(node_id: str, edges: List[Dict], action_command: str) -> Optional[Dict]:
    """
    Find edge from node_id that contains the specified action command in its action sets.
    
    Args:
        node_id: Source node ID
        edges: List of edge dictionaries 
        action_command: Action command to search for (e.g., 'tap_coordinates', 'press_key')
        
    Returns:
        Edge dictionary containing the action, or None if not found
    """
    source_edges = find_edges_from_node(node_id, edges)
    
    for edge in source_edges:
        action_sets = edge.get('action_sets', [])
        for action_set in action_sets:
            actions = action_set.get('actions', [])
            for action in actions:
                if action.get('command') == action_command:
                    return edge
    
    return None


def get_node_sub_trees_with_actions(node_id: str, tree_id: str, team_id: str) -> Dict:
    """
    Get all sub-trees for a node and return their nodes and edges for action checking.
    
    Args:
        node_id: Node ID to get sub-trees for
        tree_id: Tree ID
        team_id: Team ID
        
    Returns:
        Dict with success status and sub-tree data
    """
    from shared.src.lib.database.navigation_trees_db import get_node_sub_trees, get_full_tree
    
    # Get sub-trees for this node
    sub_trees_result = get_node_sub_trees(tree_id, node_id, team_id)
    if not sub_trees_result.get('success'):
        return {'success': False, 'error': sub_trees_result.get('error'), 'sub_trees': [], 'all_nodes': [], 'all_edges': []}
    
    sub_trees = sub_trees_result.get('sub_trees', [])
    all_nodes = []
    all_edges = []
    
    # Load nodes and edges from all sub-trees
    for sub_tree in sub_trees:
        sub_tree_id = sub_tree.get('id')
        if sub_tree_id:
            tree_data = get_full_tree(sub_tree_id, team_id)
            if tree_data.get('success'):
                all_nodes.extend(tree_data.get('nodes', []))
                all_edges.extend(tree_data.get('edges', []))
    
    return {
        'success': True,
        'sub_trees': sub_trees,
        'all_nodes': all_nodes,
        'all_edges': all_edges
    }


def find_action_in_nested_trees(source_node_id: str, tree_id: str, nodes: List[Dict], edges: List[Dict], action_command: str, team_id: str) -> Dict:
    """
    Find action in main tree and sub-trees of the specific source node only.
    
    Args:
        source_node_id: Source node ID
        tree_id: Tree ID
        nodes: List of nodes in main tree
        edges: List of edges in main tree
        action_command: Action command to search for
        team_id: Team ID
        
    Returns:
        Dict with success status and edge data if found
    """
    
    # First check in the main tree
    action_edge = find_edge_by_target_label(source_node_id, edges, nodes, action_command)
    if action_edge:
        return {'success': True, 'edge': action_edge, 'tree_type': 'main', 'tree_id': tree_id}
    
    action_edge = find_edge_with_action_command(source_node_id, edges, action_command)
    if action_edge:
        return {'success': True, 'edge': action_edge, 'tree_type': 'main', 'tree_id': tree_id}
    
    # Check sub-trees for this specific node only
    print(f"🔍 [navigation_executor_helpers] Checking sub-trees for node: {source_node_id}")
    sub_trees_data = get_node_sub_trees_with_actions(source_node_id, tree_id, team_id)
    
    if not sub_trees_data.get('success') or not sub_trees_data.get('sub_trees'):
        print(f"🔍 [navigation_executor_helpers] Node {source_node_id} has no sub-trees")
        return {'success': False, 'error': f"Action '{action_command}' not found in main tree and node has no sub-trees"}
    
    sub_nodes = sub_trees_data.get('all_nodes', [])
    sub_edges = sub_trees_data.get('all_edges', [])
    sub_trees = sub_trees_data.get('sub_trees', [])
    
    print(f"🔍 [navigation_executor_helpers] Found {len(sub_trees)} sub-trees with {len(sub_nodes)} nodes and {len(sub_edges)} edges")
    
    # Simple search: try to find action in any sub-tree node
    for node in sub_nodes:
        node_id = node.get('node_id')
        if node_id:
            # Check by target label
            sub_action_edge = find_edge_by_target_label(node_id, sub_edges, sub_nodes, action_command)
            if sub_action_edge:
                return {'success': True, 'edge': sub_action_edge, 'tree_type': 'sub', 'tree_id': sub_trees[0].get('id'), 'source_node_id': node_id}
            
            # Check by action command
            sub_action_edge = find_edge_with_action_command(node_id, sub_edges, action_command)
            if sub_action_edge:
                return {'success': True, 'edge': sub_action_edge, 'tree_type': 'sub', 'tree_id': sub_trees[0].get('id'), 'source_node_id': node_id}
    
    return {'success': False, 'error': f"Action '{action_command}' not found in main tree or sub-trees"}

