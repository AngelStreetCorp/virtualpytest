"""
Graph Utilities - Pure functions for graph construction

Reusable helpers for building ReactFlow graph structures.
NO business logic, NO state - just pure utilities.
"""

from typing import Dict, List, Any, Tuple


def create_node(node_id: str, 
                node_type: str, 
                position: Tuple[int, int],
                data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a graph node with proper structure
    
    Args:
        node_id: Unique node identifier
        node_type: Type (start, navigation, action, verification, success, failure)
        position: (x, y) coordinates
        data: Node data dictionary
        
    Returns:
        Formatted node dictionary
    """
    return {
        'id': node_id,
        'type': node_type,
        'position': {'x': position[0], 'y': position[1]},
        'data': data
    }


def create_edge(edge_id: str,
                source: str,
                target: str,
                edge_type: str = 'success',
                source_handle: str = 'success') -> Dict[str, Any]:
    """
    Create a graph edge with proper structure
    
    Args:
        edge_id: Unique edge identifier
        source: Source node ID
        target: Target node ID
        edge_type: Edge type (success, failure)
        source_handle: Source handle (success, failure)
        
    Returns:
        Formatted edge dictionary
    """
    return {
        'id': edge_id,
        'source': source,
        'target': target,
        'sourceHandle': source_handle,
        'type': edge_type
    }


def create_simple_navigation_graph(target_node: str, target_node_label: str = None) -> Dict[str, Any]:
    """
    Create a simple 3-node graph for direct navigation
    
    Used for exact match shortcuts (no AI needed)
    
    Args:
        target_node: Navigation target node ID
        target_node_label: Optional label override
        
    Returns:
        Complete graph with nodes and edges
    """
    label = target_node_label or target_node
    
    nodes = [
        create_node('start', 'start', (100, 100), {'label': 'START'}),
        create_node('nav1', 'navigation', (100, 200), {
            'label': f'navigation_1:{label}',
            'target_node': target_node,
            'target_node_id': target_node,
            'action_type': 'navigation'
        }),
        create_node('success', 'success', (100, 300), {'label': 'SUCCESS'})
    ]
    
    edges = [
        create_edge('e1', 'start', 'nav1'),
        create_edge('e2', 'nav1', 'success')
    ]
    
    return {'nodes': nodes, 'edges': edges}


def validate_graph_structure(graph: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate graph has proper structure
    
    Checks:
    - Has 'nodes' and 'edges' keys
    - Nodes have required fields: id, type, position, data
    - Edges have required fields: id, source, target
    - Has exactly one start node
    - Has at least one terminal node (success/failure)
    - All edge references point to existing nodes
    
    Args:
        graph: Graph dictionary to validate
        
    Returns:
        (is_valid, error_messages)
    """
    errors = []
    
    # Check top-level structure
    if not isinstance(graph, dict):
        return False, ["Graph must be a dictionary"]
    
    if 'nodes' not in graph:
        errors.append("Missing 'nodes' key")
    if 'edges' not in graph:
        errors.append("Missing 'edges' key")
    
    if errors:
        return False, errors
    
    nodes = graph.get('nodes', [])
    edges = graph.get('edges', [])
    
    # Check nodes
    if not nodes:
        errors.append("Graph must have at least one node")
        return False, errors
    
    node_ids = set()
    start_count = 0
    terminal_count = 0
    
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"Node {idx} is not a dictionary")
            continue
        
        # Check required fields
        if 'id' not in node:
            errors.append(f"Node {idx} missing 'id' field")
        else:
            node_ids.add(node['id'])
        
        if 'type' not in node:
            errors.append(f"Node {node.get('id', idx)} missing 'type' field")
        else:
            node_type = node['type']
            if node_type == 'start':
                start_count += 1
            elif node_type in ['success', 'failure']:
                terminal_count += 1
        
        if 'position' not in node:
            errors.append(f"Node {node.get('id', idx)} missing 'position' field")
        
        if 'data' not in node:
            errors.append(f"Node {node.get('id', idx)} missing 'data' field")
    
    # Check start/terminal nodes
    if start_count == 0:
        errors.append("Graph must have exactly one 'start' node")
    elif start_count > 1:
        errors.append(f"Graph has {start_count} start nodes (should be 1)")
    
    if terminal_count == 0:
        errors.append("Graph must have at least one terminal node (success/failure)")
    
    # Check edges
    for idx, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"Edge {idx} is not a dictionary")
            continue
        
        # Check required fields
        if 'id' not in edge:
            errors.append(f"Edge {idx} missing 'id' field")
        
        if 'source' not in edge:
            errors.append(f"Edge {edge.get('id', idx)} missing 'source' field")
        elif edge['source'] not in node_ids:
            errors.append(f"Edge {edge.get('id', idx)} references non-existent source: {edge['source']}")
        
        if 'target' not in edge:
            errors.append(f"Edge {edge.get('id', idx)} missing 'target' field")
        elif edge['target'] not in node_ids:
            errors.append(f"Edge {edge.get('id', idx)} references non-existent target: {edge['target']}")
    
    return len(errors) == 0, errors


def calculate_auto_layout(nodes: List[Dict[str, Any]], 
                          vertical_spacing: int = 100,
                          start_x: int = 100,
                          start_y: int = 100) -> List[Dict[str, Any]]:
    """
    Auto-layout nodes vertically
    
    Simple vertical stacking for clean visualization
    
    Args:
        nodes: List of nodes (will be modified in place)
        vertical_spacing: Space between nodes
        start_x: Starting X position
        start_y: Starting Y position
        
    Returns:
        Updated nodes list
    """
    for idx, node in enumerate(nodes):
        node['position'] = {
            'x': start_x,
            'y': start_y + (idx * vertical_spacing)
        }
    
    return nodes


def extract_navigation_targets(graph: Dict[str, Any]) -> List[str]:
    """
    Extract all navigation target nodes from graph
    
    Args:
        graph: Graph dictionary
        
    Returns:
        List of target node IDs
    """
    targets = []
    
    for node in graph.get('nodes', []):
        if node.get('type') == 'navigation':
            data = node.get('data', {})
            target = data.get('target_node') or data.get('target_node_id')
            if target:
                targets.append(target)
    
    return targets


def count_blocks_by_type(graph: Dict[str, Any]) -> Dict[str, int]:
    """
    Count nodes by type
    
    Args:
        graph: Graph dictionary
        
    Returns:
        {'navigation': int, 'action': int, 'verification': int, 'other': int, 'total': int}
    """
    nodes = graph.get('nodes', [])
    
    return {
        'navigation': len([n for n in nodes if n.get('type') == 'navigation']),
        'action': len([n for n in nodes if n.get('type') == 'action']),
        'verification': len([n for n in nodes if n.get('type') == 'verification']),
        'other': len([n for n in nodes if n.get('type') not in ['start', 'success', 'failure', 'navigation', 'action', 'verification']]),
        'total': len(nodes),
    }

