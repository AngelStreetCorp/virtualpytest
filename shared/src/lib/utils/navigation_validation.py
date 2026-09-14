"""
Validation functions for unified navigation system
Provides health checks and integrity validation for nested tree pathfinding
"""

import networkx as nx
from typing import Dict, List, Any, Optional
from .navigation_exceptions import NavigationError, UnifiedCacheError, PathfindingError


def validate_unified_cache_health(root_tree_id: str, team_id: str) -> Dict[str, Any]:
    """
    Validate unified cache is properly populated and functional
    
    Args:
        root_tree_id: Root tree ID to validate
        team_id: Team ID for security
        
    Returns:
        Dictionary with validation results and health metrics
    """
    try:
        from .navigation_cache import get_cached_unified_graph, get_node_tree_location, get_tree_hierarchy_metadata
        
        print(f"[@navigation:validation:validate_unified_cache_health] Validating unified cache for root tree: {root_tree_id}")
        
        # Check if unified graph exists
        unified_graph = get_cached_unified_graph(root_tree_id, team_id)
        if not unified_graph:
            return {
                'success': False,
                'error': 'No unified graph found in cache',
                'cache_populated': False,
                'recommendations': ['Run load_navigation_tree_with_hierarchy() to populate unified cache']
            }
        
        # Validate graph structure
        node_count = len(unified_graph.nodes)
        edge_count = len(unified_graph.edges)
        
        if node_count == 0:
            return {
                'success': False,
                'error': 'Unified graph has no nodes',
                'cache_populated': True,
                'graph_empty': True
            }
        
        # Check for cross-tree edges
        cross_tree_edges = []
        for from_node, to_node, edge_data in unified_graph.edges(data=True):
            if edge_data.get('edge_type') in ['ENTER_SUBTREE', 'EXIT_SUBTREE']:
                cross_tree_edges.append({
                    'from': from_node,
                    'to': to_node,
                    'type': edge_data.get('edge_type')
                })
        
        # Check tree context metadata
        trees_represented = set()
        for node_id, node_data in unified_graph.nodes(data=True):
            tree_id = node_data.get('tree_id')
            if tree_id:
                trees_represented.add(tree_id)
        
        # Validate connectivity
        is_strongly_connected = nx.is_strongly_connected(unified_graph)
        is_weakly_connected = nx.is_weakly_connected(unified_graph)
        
        # Check for isolated components
        weakly_connected_components = list(nx.weakly_connected_components(unified_graph))
        
        validation_result = {
            'success': True,
            'cache_populated': True,
            'graph_metrics': {
                'total_nodes': node_count,
                'total_edges': edge_count,
                'cross_tree_edges': len(cross_tree_edges),
                'trees_represented': len(trees_represented)
            },
            'connectivity': {
                'strongly_connected': is_strongly_connected,
                'weakly_connected': is_weakly_connected,
                'connected_components': len(weakly_connected_components)
            },
            'cross_tree_capabilities': {
                'has_cross_tree_edges': len(cross_tree_edges) > 0,
                'cross_tree_edge_types': list(set([e['type'] for e in cross_tree_edges]))
            },
            'trees_in_graph': list(trees_represented)
        }
        
        # Add warnings for potential issues
        warnings = []
        if not is_weakly_connected:
            warnings.append(f"Graph has {len(weakly_connected_components)} disconnected components")
        if len(cross_tree_edges) == 0 and len(trees_represented) > 1:
            warnings.append("Multiple trees detected but no cross-tree edges found")
        
        if warnings:
            validation_result['warnings'] = warnings
        
        print(f"[@navigation:validation:validate_unified_cache_health] Validation complete: {node_count} nodes, {edge_count} edges, {len(trees_represented)} trees")
        
        return validation_result
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Cache validation failed: {str(e)}",
            'cache_populated': False
        }


def validate_tree_hierarchy_integrity(hierarchy_data: List[Dict]) -> Dict[str, Any]:
    """
    Validate tree hierarchy has no broken relationships
    
    Args:
        hierarchy_data: List of tree data dictionaries
        
    Returns:
        Dictionary with integrity validation results
    """
    try:
        print(f"[@navigation:validation:validate_tree_hierarchy_integrity] Validating hierarchy with {len(hierarchy_data)} trees")
        
        if not hierarchy_data:
            return {
                'success': False,
                'error': 'No hierarchy data provided',
                'tree_count': 0
            }
        
        # Track tree relationships
        tree_ids = set()
        parent_child_map = {}  # parent_tree_id -> [child_tree_ids]
        child_parent_map = {}  # child_tree_id -> parent_tree_id
        depth_map = {}  # tree_id -> depth
        root_trees = []
        
        # First pass: collect all tree information
        for tree_data in hierarchy_data:
            tree_info = tree_data.get('tree_info', {})
            tree_id = tree_data.get('tree_id')
            
            if not tree_id:
                return {
                    'success': False,
                    'error': 'Tree data missing tree_id',
                    'invalid_tree_data': tree_data
                }
            
            tree_ids.add(tree_id)
            depth = tree_info.get('tree_depth', 0)
            depth_map[tree_id] = depth
            
            parent_tree_id = tree_info.get('parent_tree_id')
            is_root = tree_info.get('is_root_tree', False)
            
            if is_root or depth == 0:
                root_trees.append(tree_id)
            
            if parent_tree_id:
                child_parent_map[tree_id] = parent_tree_id
                if parent_tree_id not in parent_child_map:
                    parent_child_map[parent_tree_id] = []
                parent_child_map[parent_tree_id].append(tree_id)
        
        # Validation checks
        validation_issues = []
        
        # Check 1: Exactly one root tree
        if len(root_trees) != 1:
            validation_issues.append(f"Expected exactly 1 root tree, found {len(root_trees)}: {root_trees}")
        
        # Check 2: All parent references are valid
        for child_id, parent_id in child_parent_map.items():
            if parent_id not in tree_ids:
                validation_issues.append(f"Tree {child_id} references non-existent parent {parent_id}")
        
        # Check 3: Depth consistency
        for tree_id, depth in depth_map.items():
            if tree_id in child_parent_map:
                parent_id = child_parent_map[tree_id]
                parent_depth = depth_map.get(parent_id, 0)
                expected_depth = parent_depth + 1
                if depth != expected_depth:
                    validation_issues.append(f"Tree {tree_id} has depth {depth}, expected {expected_depth} based on parent {parent_id}")
        
        # Check 4: No circular references
        def has_circular_reference(tree_id, visited=None):
            if visited is None:
                visited = set()
            if tree_id in visited:
                return True
            visited.add(tree_id)
            parent_id = child_parent_map.get(tree_id)
            if parent_id:
                return has_circular_reference(parent_id, visited)
            return False
        
        for tree_id in tree_ids:
            if has_circular_reference(tree_id):
                validation_issues.append(f"Circular reference detected involving tree {tree_id}")
        
        # Check 5: Maximum depth constraint
        max_depth = max(depth_map.values()) if depth_map else 0
        if max_depth > 5:
            validation_issues.append(f"Maximum depth {max_depth} exceeds limit of 5")
        
        # Build hierarchy statistics
        hierarchy_stats = {
            'total_trees': len(tree_ids),
            'root_trees': len(root_trees),
            'max_depth': max_depth,
            'trees_by_depth': {},
            'parent_child_relationships': len(child_parent_map)
        }
        
        # Count trees by depth
        for depth in range(max_depth + 1):
            trees_at_depth = [tid for tid, d in depth_map.items() if d == depth]
            hierarchy_stats['trees_by_depth'][depth] = len(trees_at_depth)
        
        if validation_issues:
            return {
                'success': False,
                'error': 'Hierarchy integrity issues found',
                'validation_issues': validation_issues,
                'hierarchy_stats': hierarchy_stats
            }
        
        print(f"[@navigation:validation:validate_tree_hierarchy_integrity] Hierarchy validation passed: {len(tree_ids)} trees, max depth {max_depth}")
        
        return {
            'success': True,
            'hierarchy_stats': hierarchy_stats,
            'validation_summary': f"Valid hierarchy: {len(tree_ids)} trees, max depth {max_depth}"
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Hierarchy validation failed: {str(e)}"
        }


def validate_cross_tree_edges(unified_graph: nx.DiGraph) -> Dict[str, Any]:
    """
    Validate ENTER_SUBTREE and EXIT_SUBTREE edges are correct
    
    Args:
        unified_graph: NetworkX unified graph
        
    Returns:
        Dictionary with cross-tree edge validation results
    """
    try:
        print(f"[@navigation:validation:validate_cross_tree_edges] Validating cross-tree edges in unified graph")
        
        if not unified_graph:
            return {
                'success': False,
                'error': 'No unified graph provided'
            }
        
        # Find all cross-tree edges
        enter_subtree_edges = []
        exit_subtree_edges = []
        normal_cross_tree_edges = []
        
        for from_node, to_node, edge_data in unified_graph.edges(data=True):
            edge_type = edge_data.get('edge_type', 'NORMAL')
            
            # Get tree context for nodes
            from_node_data = unified_graph.nodes.get(from_node, {})
            to_node_data = unified_graph.nodes.get(to_node, {})
            from_tree_id = from_node_data.get('tree_id')
            to_tree_id = to_node_data.get('tree_id')
            
            if from_tree_id != to_tree_id:  # Cross-tree edge
                edge_info = {
                    'from_node': from_node,
                    'to_node': to_node,
                    'from_tree': from_tree_id,
                    'to_tree': to_tree_id,
                    'edge_type': edge_type,
                    'is_virtual': edge_data.get('is_virtual', False)
                }
                
                if edge_type == 'ENTER_SUBTREE':
                    enter_subtree_edges.append(edge_info)
                elif edge_type == 'EXIT_SUBTREE':
                    exit_subtree_edges.append(edge_info)
                else:
                    normal_cross_tree_edges.append(edge_info)
        
        # Validation checks
        validation_issues = []
        
        # Check 1: ENTER_SUBTREE edges should be virtual
        for edge in enter_subtree_edges:
            if not edge['is_virtual']:
                validation_issues.append(f"ENTER_SUBTREE edge {edge['from_node']} -> {edge['to_node']} should be virtual")
        
        # Check 2: EXIT_SUBTREE edges should be virtual
        for edge in exit_subtree_edges:
            if not edge['is_virtual']:
                validation_issues.append(f"EXIT_SUBTREE edge {edge['from_node']} -> {edge['to_node']} should be virtual")
        
        # Check 3: Normal cross-tree edges should have proper metadata
        for edge in normal_cross_tree_edges:
            if not edge['from_tree'] or not edge['to_tree']:
                validation_issues.append(f"Cross-tree edge {edge['from_node']} -> {edge['to_node']} missing tree metadata")
        
        cross_tree_stats = {
            'total_cross_tree_edges': len(enter_subtree_edges) + len(exit_subtree_edges) + len(normal_cross_tree_edges),
            'enter_subtree_edges': len(enter_subtree_edges),
            'exit_subtree_edges': len(exit_subtree_edges),
            'normal_cross_tree_edges': len(normal_cross_tree_edges)
        }
        
        if validation_issues:
            return {
                'success': False,
                'error': 'Cross-tree edge validation issues found',
                'validation_issues': validation_issues,
                'cross_tree_stats': cross_tree_stats
            }
        
        print(f"[@navigation:validation:validate_cross_tree_edges] Cross-tree edge validation passed: {cross_tree_stats['total_cross_tree_edges']} edges")
        
        return {
            'success': True,
            'cross_tree_stats': cross_tree_stats,
            'validation_summary': f"Valid cross-tree edges: {cross_tree_stats['total_cross_tree_edges']} total"
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f"Cross-tree edge validation failed: {str(e)}"
        }


def validate_complete_unified_system(root_tree_id: str, team_id: str) -> Dict[str, Any]:
    """
    Run complete validation of the unified navigation system
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        
    Returns:
        Complete validation report
    """
    try:
        print(f"[@navigation:validation:validate_complete_unified_system] Running complete system validation for root tree: {root_tree_id}")
        
        validation_report = {
            'root_tree_id': root_tree_id,
            'team_id': team_id,
            'validation_timestamp': __import__('datetime').datetime.now().isoformat(),
            'overall_success': True,
            'validations': {}
        }
        
        # 1. Validate unified cache health
        cache_validation = validate_unified_cache_health(root_tree_id, team_id)
        validation_report['validations']['cache_health'] = cache_validation
        if not cache_validation['success']:
            validation_report['overall_success'] = False
        
        # 2. If cache is healthy, validate cross-tree edges
        if cache_validation['success'] and cache_validation.get('cache_populated'):
            from .navigation_cache import get_cached_unified_graph
            unified_graph = get_cached_unified_graph(root_tree_id, team_id)
            
            if unified_graph:
                cross_tree_validation = validate_cross_tree_edges(unified_graph)
                validation_report['validations']['cross_tree_edges'] = cross_tree_validation
                if not cross_tree_validation['success']:
                    validation_report['overall_success'] = False
        
        # 3. Validate hierarchy integrity (requires loading hierarchy)
        try:
            from .navigation_utils import discover_complete_hierarchy
            hierarchy_data = discover_complete_hierarchy(root_tree_id, team_id, "validation")
            
            if hierarchy_data:
                hierarchy_validation = validate_tree_hierarchy_integrity(hierarchy_data)
                validation_report['validations']['hierarchy_integrity'] = hierarchy_validation
                if not hierarchy_validation['success']:
                    validation_report['overall_success'] = False
        except Exception as hierarchy_error:
            validation_report['validations']['hierarchy_integrity'] = {
                'success': False,
                'error': f"Could not load hierarchy for validation: {str(hierarchy_error)}"
            }
            validation_report['overall_success'] = False
        
        # Generate summary
        successful_validations = len([v for v in validation_report['validations'].values() if v.get('success')])
        total_validations = len(validation_report['validations'])
        
        validation_report['summary'] = {
            'successful_validations': successful_validations,
            'total_validations': total_validations,
            'success_rate': f"{successful_validations}/{total_validations}",
            'overall_result': 'PASS' if validation_report['overall_success'] else 'FAIL'
        }
        
        print(f"[@navigation:validation:validate_complete_unified_system] Complete validation: {validation_report['summary']['success_rate']} - {validation_report['summary']['overall_result']}")
        
        return validation_report
        
    except Exception as e:
        return {
            'overall_success': False,
            'error': f"Complete system validation failed: {str(e)}",
            'root_tree_id': root_tree_id,
            'team_id': team_id
        }