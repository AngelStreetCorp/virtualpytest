"""
Unified Pathfinding System for Navigation Trees
Uses NetworkX for cross-tree shortest path calculations with fail-early behavior

DOM-SPECIFIC OPTIMIZATION:
- Sibling Shortcuts: Nodes sharing the same parent (e.g., nav bar) are directly reachable
- Example: home_tvguide → home_replay uses the same action as home → home_replay
"""

import networkx as nx
from typing import List, Dict, Optional, Tuple
from shared.src.lib.utils.navigation_exceptions import UnifiedCacheError, PathfindingError


def find_shortest_path(
    tree_id: str,
    target_node_id: str,
    team_id: str,
    start_node_id: str = None,
    variant: Optional[str] = None,
    exclude_node_ids: Optional[set] = None,
) -> List[Dict]:
    """
    Find shortest path using ONLY unified graph - no fallback to single-tree
    FAIL EARLY: If unified cache missing, operation fails immediately

    Args:
        tree_id: Navigation tree ID (treated as root tree for unified pathfinding)
        target_node_id: Target node to navigate to (can be node ID or label)
        team_id: Team ID for security
        start_node_id: Starting node (if None, uses entry point; can be node ID or label)
        variant: Variant scope name (None / '' = base). Pathfinding picks the
            cached graph for this scope so different variants can have
            structurally different `action_sets` per edge.
        exclude_node_ids: Optional set of node IDs to remove from the graph
            before searching. Used by conditional-edge recovery to force a
            FORWARD-only path from the landed sibling to the target. When set,
            recovery hides BOTH the excluded source node(s) AND every reverse
            action-set edge (`is_reverse_edge`) — so the recovery can neither
            route back through the diverging conditional edge nor take a reverse
            hop (e.g. BACK) to fake a path to the target. Both would loop.

    Returns:
        List of navigation steps

    Raises:
        UnifiedCacheError: If unified cache is not available
        PathfindingError: If no path can be found
    """
    # Use unified pathfinding ONLY - NO FALLBACK
    unified_result = find_shortest_path_unified(tree_id, target_node_id, team_id, start_node_id, variant=variant, exclude_node_ids=exclude_node_ids)
    if unified_result is not None:  # FIX: Check for None explicitly, not falsy (empty list [] is valid)
        return unified_result

    # FAIL EARLY - no fallback available
    raise PathfindingError(f"No unified path found to '{target_node_id}'. Unified pathfinding is required - no single-tree fallback available.")


def find_shortest_path_unified(
    root_tree_id: str,
    target_node_id: str,
    team_id: str,
    start_node_id: str = None,
    variant: Optional[str] = None,
    exclude_node_ids: Optional[set] = None,
) -> Optional[List[Dict]]:
    """
    Find shortest path across nested trees using unified graph
    Enhanced with fail-early behavior and clear error messages

    Args:
        root_tree_id: Root navigation tree ID
        target_node_id: Target node to navigate to (can be node ID or label)
        team_id: Team ID for security
        start_node_id: Starting node (if None, uses entry point; can be node ID or label)
        variant: Variant scope name (None / '' = base).

    Returns:
        List of navigation transitions with cross-tree context or None if no path found
    """
    # Get unified cached graph - MANDATORY
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph, get_node_tree_location, get_tree_hierarchy_metadata
    from shared.src.lib.utils.navigation_graph import get_entry_points, get_node_info

    unified_graph = get_cached_unified_graph(root_tree_id, team_id, variant=variant)
    if not unified_graph:
        raise UnifiedCacheError(f"No unified graph cached for root tree {root_tree_id}. Unified pathfinding is required - no fallback available.")
    
    # Note: Action nodes ARE allowed - pathfinding finds the node containing the action
    # The navigation executor will handle action execution without updating device position
    
    # Resolve target_node_id if it's a label instead of UUID (including action nodes)
    actual_target_node = target_node_id
    target_resolved_by_label = False
    
    print(f"[@pathfinding] 🎯 TARGET NODE RESOLUTION:")
    print(f"[@pathfinding]   → Requested target_node_id: {target_node_id}")
    print(f"[@pathfinding]   → Is in unified graph? {target_node_id in unified_graph.nodes}")
    
    if target_node_id not in unified_graph.nodes:
        print(f"[@pathfinding]   → Node ID not found, trying to resolve by label...")
        # Collect ALL nodes with matching label (there may be duplicates across trees)
        matching_nodes = []
        for node_id, node_data in unified_graph.nodes(data=True):
            if node_data.get('label', '') == target_node_id:
                matching_nodes.append(node_id)
        
        # If no exact match, try case-insensitive
        if not matching_nodes:
            for node_id, node_data in unified_graph.nodes(data=True):
                if node_data.get('label', '').lower() == target_node_id.lower():
                    matching_nodes.append(node_id)
        
        # If we found matches, prefer the one in the root tree
        if matching_nodes:
            if len(matching_nodes) > 1:
                print(f"[@pathfinding]   ⚠️  Found {len(matching_nodes)} nodes with label '{target_node_id}': {matching_nodes}")
                # Prefer nodes from root tree
                for node_id in matching_nodes:
                    node_data = unified_graph.nodes[node_id]
                    if node_data.get('tree_id') == root_tree_id:
                        actual_target_node = node_id
                        print(f"[@pathfinding]   ✅ Resolved by label (preferred root tree)! '{target_node_id}' → {actual_target_node}")
                        break
                else:
                    # No root tree match, use first one
                    actual_target_node = matching_nodes[0]
                    print(f"[@pathfinding]   ✅ Resolved by label (first match)! '{target_node_id}' → {actual_target_node}")
            else:
                actual_target_node = matching_nodes[0]
                print(f"[@pathfinding]   ✅ Resolved by label! '{target_node_id}' → {actual_target_node}")
            target_resolved_by_label = True
    
    # Determine starting node
    actual_start_node = start_node_id
    start_resolved_by_label = False
    if start_node_id:
        # Resolve start_node_id if it's a label instead of UUID
        if start_node_id not in unified_graph.nodes:
            for node_id, node_data in unified_graph.nodes(data=True):
                if node_data.get('label', '') == start_node_id:
                    actual_start_node = node_id
                    start_resolved_by_label = True
                    break
            else:
                # Try case-insensitive search
                for node_id, node_data in unified_graph.nodes(data=True):
                    if node_data.get('label', '').lower() == start_node_id.lower():
                        actual_start_node = node_id
                        start_resolved_by_label = True
                        break
                else:
                    # If start_node_id couldn't be resolved, treat it as None (fallback to entry)
                    print(f"[@navigation:pathfinding:find_shortest_path_unified] Warning: start_node_id '{start_node_id}' not found in graph, falling back to entry point")
                    actual_start_node = None
    
    if not actual_start_node:
        entry_points = get_entry_points(unified_graph)
        
        if not entry_points:
            nodes = list(unified_graph.nodes())
            if not nodes:
                raise PathfindingError("No nodes in unified graph")
            actual_start_node = nodes[0]
        else:
            # Prioritize dedicated entry node over home node
            dedicated_entry = None
            for entry_id in entry_points:
                entry_info = get_node_info(unified_graph, entry_id)
                if entry_info and entry_info.get('node_type') == 'entry':
                    dedicated_entry = entry_id
                    break
            
            actual_start_node = dedicated_entry if dedicated_entry else entry_points[0]
    
    # Validate nodes exist
    if actual_start_node not in unified_graph.nodes:
        raise PathfindingError(f"Start node {actual_start_node} not found in unified graph")
    
    # FAIL EARLY if target not found - clear, actionable error
    if actual_target_node not in unified_graph.nodes:
        available_nodes = list(unified_graph.nodes())
        
        # Log detailed information about available nodes
        print(f"[@pathfinding] ❌ TARGET NODE NOT FOUND!")
        print(f"[@pathfinding]   → Requested: {actual_target_node}")
        print(f"[@pathfinding]   → Available nodes ({len(available_nodes)}):")
        for node_id in available_nodes[:20]:  # Show first 20 nodes
            node_data = unified_graph.nodes[node_id]
            node_label = node_data.get('label', 'NO_LABEL')
            node_type = node_data.get('type', 'NO_TYPE')
            print(f"[@pathfinding]      • {node_id} (label: '{node_label}', type: '{node_type}')")
        if len(available_nodes) > 20:
            print(f"[@pathfinding]      ... and {len(available_nodes) - 20} more nodes")
        
        raise PathfindingError(f"Target node {actual_target_node} not found in unified graph. Available nodes: {available_nodes}")
    
    # Check if we're already at the target
    if actual_start_node == actual_target_node:
        print(f"[@navigation:pathfinding:find_shortest_path_unified] Already at target node {actual_target_node}")
        return []
    
    # Forward-only recovery: search on a graph that hides BOTH (a) the excluded
    # nodes — the source we just diverged from — AND (b) every reverse
    # action-set edge (`is_reverse_edge`, the `action_sets[1]` leg, e.g. a BACK
    # key). Excluding only the source is NOT enough to stay forward-only: a
    # reverse edge gives an alternate route from the landed sibling back to the
    # target that never passes through the source (e.g. sibling --BACK--> target),
    # which is exactly the conditional-recovery loop we want to avoid. With
    # reverse edges hidden, a sibling reachable only by going backward has no
    # forward path to the target, so recovery returns nothing and the executor
    # accepts "arrived on sibling" as success. If a genuine forward chain to the
    # exact target exists it is still found and used.
    #
    # `restricted_view` keeps every non-hidden NODE present (unlike edge_subgraph,
    # which would drop now-isolated nodes and make shortest_path raise
    # NodeNotFound instead of NetworkXNoPath). Edge-data extraction below still
    # reads `unified_graph`; every edge on the returned path is a forward edge
    # present in the full graph too.
    search_graph = unified_graph
    if exclude_node_ids:
        hidden_reverse_edges = [
            (u, v) for u, v, d in unified_graph.edges(data=True)
            if d.get('is_reverse_edge')
        ]
        search_graph = nx.restricted_view(unified_graph, list(exclude_node_ids), hidden_reverse_edges)
        print(f"[@navigation:pathfinding:find_shortest_path_unified] Forward-only recovery: hiding {len(exclude_node_ids)} source node(s) and {len(hidden_reverse_edges)} reverse edge(s)")

    try:
        # Use NetworkX shortest path algorithm on the (possibly filtered) graph
        path = nx.shortest_path(search_graph, actual_start_node, actual_target_node)
        
        # Convert path to navigation transitions with cross-tree support
        navigation_transitions = []
        transition_number = 1
        total_actions = 0
        total_retry_actions = 0
        total_failure_actions = 0
        cross_tree_transitions = []
        
        for i in range(len(path) - 1):
            from_node = path[i]
            to_node = path[i + 1]
            
            # Get node information
            from_node_info = get_node_info(unified_graph, from_node) or {}
            to_node_info = get_node_info(unified_graph, to_node) or {}
            
            # Get edge data - check multiple possible action formats
            edge_data = unified_graph.edges[from_node, to_node] if unified_graph.has_edge(from_node, to_node) else {}
            
            # Use standardized 2-action-set structure: forward (index 0) then reverse (index 1)
            action_sets = edge_data.get('action_sets', [])
            
            if not action_sets:
                raise PathfindingError(f"Edge {from_node} -> {to_node} missing action_sets")
            
            # Always use forward action set (first in array) for regular pathfinding
            forward_set = action_sets[0]
            actions_list = forward_set.get('actions', [])
            retry_actions_list = forward_set.get('retry_actions') or []
            failure_actions_list = forward_set.get('failure_actions') or []
            verifications_list = to_node_info.get('verifications', [])
            
            # DEBUG: Log verifications for Home node
            if to_node_info.get('label') == 'home':
                print(f"[@DEBUG:pathfinding] Home node verifications: {verifications_list}")
            
            # Count actions for summary
            total_actions += len(actions_list)
            total_retry_actions += len(retry_actions_list)
            total_failure_actions += len(failure_actions_list)
            
            # Check for cross-tree transition
            transition_type = edge_data.get('edge_type', 'NORMAL')
            is_cross_tree = transition_type in ['ENTER_SUBTREE', 'EXIT_SUBTREE']

            # Conditional edge: this step shares its forward action_set with
            # sibling edges from the same source, so after running the action
            # the device may land on this target OR on one of the siblings.
            # Surface the flag + the sibling destination labels so the executor
            # can force a verify on this step (branch detection) and the goto
            # preview can badge it as "one of several possible paths".
            is_conditional = bool(edge_data.get('is_conditional'))
            sibling_labels = []
            if is_conditional:
                for sib_id in edge_data.get('sibling_node_ids', []):
                    sib_info = get_node_info(unified_graph, sib_id) or {}
                    sibling_labels.append(sib_info.get('label', sib_id))
            
            # Get tree context
            from_tree_id = from_node_info.get('tree_id', '')
            to_tree_id = to_node_info.get('tree_id', '')
            tree_context_change = from_tree_id != to_tree_id
            
            if is_cross_tree:
                cross_tree_transitions.append(f"{from_node_info.get('label', from_node)} → {to_node_info.get('label', to_node)} ({transition_type})")
            
            # Create navigation transition with action_sets structure ONLY
            navigation_transition = {
                'transition_number': transition_number,
                'step_number': transition_number,  # Add step_number for action_utils compatibility
                'from_node_id': from_node,
                'to_node_id': to_node,
                'from_node_label': from_node_info.get('label', from_node),
                'to_node_label': to_node_info.get('label', to_node),
                'from_tree_id': from_tree_id,
                'to_tree_id': to_tree_id,  # ✅ ONE TRUTH: target tree (used by executor for DB calls)
                'transition_type': transition_type,
                'tree_context_change': tree_context_change,
                'actions': actions_list,
                'retryActions': retry_actions_list,
                'failureActions': failure_actions_list,
                'action_set_id': forward_set.get('id'),  # Track forward action set used
                'original_edge_data': edge_data,  # Preserve original edge structure
                'verifications': verifications_list,
                # Per-direction final_wait_time lives on the action_set used for this step.
                'final_wait_time': forward_set.get('final_wait_time', 0),
                'edge_id': edge_data.get('edge_id', 'unknown'),
                'is_virtual': edge_data.get('is_virtual', False),
                'is_conditional': is_conditional,  # Step's destination is ambiguous (shared action with siblings)
                'sibling_labels': sibling_labels,  # Other nodes this step could land on
                # Step that LEAVES the entry point (ENTRY → home). The executor
                # force-verifies it regardless of verification_mode: it's the only
                # check that the device is actually at the assumed start. Without
                # it, a box in standby/screensaver is never detected and the
                # verification-driven recovery (retry/failure actions, e.g. POWER)
                # never fires. See _should_verify_step.
                'is_entry_transition': bool(from_node_info.get('is_entry_point', False)),
                'description': f"Navigate from '{from_node_info.get('label', from_node)}' to '{to_node_info.get('label', to_node)}'"
            }
            
            # Add cross-tree metadata if applicable
            if is_cross_tree:
                navigation_transition['cross_tree_metadata'] = {
                    'source_tree_name': from_node_info.get('tree_name', ''),
                    'target_tree_name': to_node_info.get('tree_name', ''),
                    'tree_depth_change': to_node_info.get('tree_depth', 0) - from_node_info.get('tree_depth', 0)
                }
            
            navigation_transitions.append(navigation_transition)
            transition_number += 1
        
        # Generate consolidated summary log
        start_label = unified_graph.nodes.get(actual_start_node, {}).get('label', actual_start_node)
        target_label = unified_graph.nodes.get(actual_target_node, {}).get('label', actual_target_node)
        
        summary_parts = [
            f"Path: {start_label} → {target_label}",
            f"{len(navigation_transitions)} transitions",
            f"{total_actions} actions"
        ]
        
        if total_retry_actions > 0:
            summary_parts.append(f"{total_retry_actions} retry")
        if total_failure_actions > 0:
            summary_parts.append(f"{total_failure_actions} failure")
        if cross_tree_transitions:
            summary_parts.append(f"{len(cross_tree_transitions)} cross-tree")
        if target_resolved_by_label:
            summary_parts.append(f"target: {target_node_id}→{actual_target_node}")
        
        print(f"[@navigation:pathfinding:find_shortest_path_unified] {', '.join(summary_parts)}")
        
        return navigation_transitions
        
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        # NodeNotFound can surface under forward-only recovery if the landed
        # sibling or target ends up with no forward edges in the restricted
        # view — treat it the same as "no path".
        # FALLBACK: Try from entry point to target — but NOT under exclusion.
        # Forward-only recovery excludes the source node; the entry fallback
        # ignores the exclusion set and could route back through that source,
        # re-introducing the conditional-edge loop. Fail cleanly instead.
        if not exclude_node_ids:
            print(f"[@navigation:pathfinding:find_shortest_path_unified] No direct path - trying from entry")
            entry_points = get_entry_points(unified_graph)
            if entry_points:
                try:
                    path = nx.shortest_path(unified_graph, entry_points[0], actual_target_node)
                    print(f"[@navigation:pathfinding:find_shortest_path_unified] ✅ Using entry fallback")
                    return find_shortest_path_unified(root_tree_id, actual_target_node, team_id, entry_points[0], variant=variant)
                except nx.NetworkXNoPath:
                    pass
        
        # Enhanced error logging with node labels
        start_label = "unknown"
        target_label = "unknown"
        try:
            start_node_info = get_node_info(unified_graph, actual_start_node)
            if start_node_info:
                start_label = start_node_info.get('label', 'unknown')
            
            target_node_info = get_node_info(unified_graph, actual_target_node)
            if target_node_info:
                target_label = target_node_info.get('label', 'unknown')
        except:
            pass  # Fall back to 'unknown' if label lookup fails
            
        print(f"[@navigation:pathfinding:find_shortest_path_unified] No path found from {start_label} ({actual_start_node}) to {target_label} ({actual_target_node})")
        raise PathfindingError(f"No path found from '{start_label} ({actual_start_node})' to '{target_label} ({actual_target_node})' in unified graph")
    except Exception as e:
        print(f"[@navigation:pathfinding:find_shortest_path_unified] Error finding path: {e}")
        raise PathfindingError(f"Error finding unified path: {str(e)}")


# Keep only essential helper functions - remove all legacy single-tree functions
def get_navigation_transitions(tree_id: str, target_node_id: str, team_id: str, current_node_id: str = None) -> List[Dict]:
    """
    Get step-by-step navigation instructions using unified pathfinding only
    """
    return find_shortest_path(tree_id, target_node_id, team_id, current_node_id)




def find_optimal_edge_validation_sequence(tree_id: str, team_id: str, subtree_root_node_id: str = None, variant: str = None) -> List[Dict]:
    """
    Find optimal sequence for validating all edges with enhanced bidirectional support.
    Uses depth-first traversal to ensure systematic coverage.

    Args:
        tree_id: Navigation tree ID
        team_id: Team ID for security
        subtree_root_node_id: Optional. If provided, validate only edges of the linked
            child tree of that node (resolved via node.child_tree_id).
        variant: Optional named-variant scope (None / '' = base). The sequence is
            built from the variant-scoped cached graph so a chosen variant's
            node/edge overrides are actually validated (see VARIANT.md §6).

    Returns:
        List of validation steps ordered for optimal traversal
    """
    print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Finding optimal validation sequence for tree {tree_id} (variant={variant or 'base'})")

    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    from shared.src.lib.utils.navigation_graph import get_node_info

    G = get_cached_unified_graph(tree_id, team_id, variant=variant)
    if not G:
        print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Failed to get graph for tree {tree_id}")
        return []

    # If subtree mode, resolve the child_tree_id linked from the entry node
    child_tree_id_filter = None
    if subtree_root_node_id:
        node_info = get_node_info(G, subtree_root_node_id) or {}
        child_tree_id_filter = node_info.get('child_tree_id')
        if not child_tree_id_filter:
            print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Node '{subtree_root_node_id}' has no child_tree_id — cannot validate subtree")
            return []
        print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Subtree mode: filtering to child_tree_id={child_tree_id_filter}")

    # Get all edges that need validation
    edges_to_validate = []
    total_edges = 0
    virtual_edges = 0
    skipped_other_tree = 0

    for u, v, data in G.edges(data=True):
        total_edges += 1
        is_virtual = data.get('is_virtual', False)

        if is_virtual:
            virtual_edges += 1
            print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Skipping virtual edge: {u} → {v}")
            continue

        if child_tree_id_filter and data.get('tree_id') != child_tree_id_filter:
            skipped_other_tree += 1
            continue

        # Include ALL non-virtual edges for validation (even without actions)
        edges_to_validate.append((u, v, data))
        action_sets = data.get('action_sets', [])
        has_actions = any(action_set.get('actions') for action_set in action_sets if action_set)
        print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Adding edge for validation: {u} → {v} (has_actions={has_actions})")

    print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Edge analysis: {total_edges} total, {virtual_edges} virtual, {skipped_other_tree} other-tree, {len(edges_to_validate)} to validate")

    if not edges_to_validate:
        print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] No edges to validate")
        return []

    print(f"[@navigation:pathfinding:find_optimal_edge_validation_sequence] Found {len(edges_to_validate)} edges to validate")

    # Use depth-first traversal for optimal validation sequence
    validation_sequence = _create_reachability_based_validation_sequence(
        G, edges_to_validate, tree_id, team_id,
        subtree_mode=bool(subtree_root_node_id),
        initial_position=subtree_root_node_id,
    )

    return validation_sequence


def _create_reachability_based_validation_sequence(G, edges_to_validate: List[Tuple],
                                                 tree_id: str, team_id: str,
                                                 subtree_mode: bool = False,
                                                 initial_position: str = None) -> List[Dict]:
    """
    Create validation sequence using depth-first traversal that goes deep into each branch before coming back.
    
    Args:
        G: NetworkX graph
        edges_to_validate: List of (from_node, to_node, edge_data) tuples
        
    Returns:
        List of validation steps ordered by depth-first traversal
    """
    from shared.src.lib.utils.navigation_graph import get_entry_points, get_node_info
    
    print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Creating depth-first validation sequence")
    
    # Build edge mapping for quick lookup INCLUDING bidirectional edges
    edge_map = {}
    bidirectional_edges = set()
    
    for u, v, data in edges_to_validate:
        edge_map[(u, v)] = data
        
        # Check if reverse direction has actions (action set at index 1)
        action_sets = data.get('action_sets', [])
        if len(action_sets) >= 2:
            reverse_set = action_sets[1]  # Index 1 = reverse action set
            if reverse_set and reverse_set.get('actions'):
                # Add reverse edge to map - reverse direction has valid actions
                edge_map[(v, u)] = data
                bidirectional_edges.add((u, v))
                bidirectional_edges.add((v, u))
                
                from_info = get_node_info(G, u) or {}
                to_info = get_node_info(G, v) or {}
                from_label = from_info.get('label', u)
                to_label = to_info.get('label', v)
                print(f"[@navigation:pathfinding] Reverse direction available: {from_label} ↔ {to_label}")
    
    print(f"[@navigation:pathfinding] Edge mapping complete: {len(edge_map)} total edges, {len(bidirectional_edges)//2} with reverse actions")
    
    # Build adjacency list for traversal
    adjacency = {}
    for u, v, data in edges_to_validate:
        if u not in adjacency:
            adjacency[u] = []
        adjacency[u].append(v)
        
        # Make adjacency symmetric for bidirectional edges to ensure all directions are traversed as children
        if (v, u) in edge_map:  # If reverse exists
            if v not in adjacency:
                adjacency[v] = []
            if u not in adjacency[v]:
                adjacency[v].append(u)  # Add reverse as child
    
    # Sort children for consistent ordering
    for node in adjacency:
        adjacency[node].sort()
    
    # Find entry points
    if subtree_mode:
        # Compute entry points within the filtered subgraph: nodes that appear
        # as edge sources but never as targets in edges_to_validate.
        sub_nodes = set()
        sub_targets = set()
        for u, v, _ in edges_to_validate:
            sub_nodes.add(u)
            sub_nodes.add(v)
            sub_targets.add(v)
        candidates = sub_nodes - sub_targets
        if candidates:
            entry_points = sorted(candidates)
        elif sub_nodes:
            entry_points = [sorted(sub_nodes)[0]]
        else:
            entry_points = []
    else:
        entry_points = get_entry_points(G)
        if not entry_points:
            # Find nodes with no incoming edges
            entry_points = [node for node in G.nodes() if G.in_degree(node) == 0]
        if not entry_points and G.nodes():
            entry_points = [list(G.nodes())[0]]
    
    print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Starting depth-first from entry points: {entry_points}")
    
    validation_sequence = []
    visited_edges = set()
    step_number = 1
    # In subtree mode, the device has been pre-navigated to `initial_position`
    # (the parent-tree entry node). Use it as the starting position so the first
    # DFS step inserts a forced-transition into the child tree.
    if subtree_mode and initial_position:
        current_position = initial_position
    else:
        current_position = entry_points[0] if entry_points else None
    recursion_stack = set()  # For cycle detection in DFS

    def depth_first_traversal(current_node, parent_node=None):
        """Recursively traverse depth-first, going deep into each branch before coming back"""
        nonlocal step_number, current_position
        
        if current_node in recursion_stack:
            print(f"[@navigation:pathfinding] Cycle detected at {current_node} - skipping recursion")
            return
        
        recursion_stack.add(current_node)
        
        # Process all children of current node depth-first
        for child_node in adjacency.get(current_node, []):
            forward_edge = (current_node, child_node)
            
            # Skip if already visited or if it's the parent (avoid immediate back-and-forth)
            if forward_edge in visited_edges or child_node == parent_node:
                continue
            
            # Add forward edge
            from_info = get_node_info(G, current_node) or {}
            to_info = get_node_info(G, child_node) or {}
            from_label = from_info.get('label', current_node)
            to_label = to_info.get('label', child_node)
            
            validation_step = _create_validation_step(G, current_node, child_node, edge_map[forward_edge], step_number, 'depth_first_forward', tree_id, team_id)
            validation_sequence.append(validation_step)
            visited_edges.add(forward_edge)
            print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Step {validation_step['step_number']}: {from_label} → {to_label} (forward)")
            step_number = validation_step['step_number'] + 1
            
            # Update position: if target is action node, stay at current node, otherwise move to target
            child_node_info = get_node_info(G, child_node) or {}
            if child_node_info.get('node_type') == 'action':
                # Action nodes don't change position - we stay where we were
                # Skip DFS recursion and return detection - we never moved!
                print(f"[@navigation:pathfinding] Action node {to_label} - staying at {from_label} (no return needed)")
                continue  # Move to next child, no recursion or return path needed
            else:
                current_position = child_node
            
            # Recursively go deeper into this child's branch (only for non-action nodes)
            depth_first_traversal(child_node, current_node)
            
            # ENHANCED RETURN EDGE DETECTION (only for non-action nodes)
            return_edge = (child_node, current_node)
            return_edge_data = None
            return_method = None
            
            # Strategy 1: Direct return edge exists
            if return_edge in edge_map and return_edge not in visited_edges:
                return_edge_data = edge_map[return_edge]
                return_method = "direct"
                print(f"[@navigation:pathfinding] Found direct return edge: {to_label} → {from_label}")
            
            # Strategy 2: Reverse direction has actions available
            elif forward_edge in bidirectional_edges and return_edge not in visited_edges:
                return_edge_data = edge_map[forward_edge]  # Same edge data
                return_method = "reverse_actions"
                print(f"[@navigation:pathfinding] Found reverse actions: {to_label} → {from_label}")
            
            # Strategy 3: Transitional edge using pathfinding (always enabled)
            elif return_edge not in visited_edges:
                try:
                    # Try to find a path back using unified pathfinding
                    transitional_path = find_shortest_path_unified(tree_id, current_node, team_id, child_node)
                    if transitional_path:
                        print(f"[@navigation:pathfinding] Using transitional path: {to_label} → {from_label} ({len(transitional_path)} steps)")
                        for i, step in enumerate(transitional_path):
                            step['step_type'] = 'transitional_return'
                            step['step_number'] = step_number + i
                            validation_sequence.append(step)
                        step_number += len(transitional_path)
                        visited_edges.add(return_edge)  # Mark as handled
                        continue
                except Exception as e:
                    print(f"[@navigation:pathfinding] Transitional path failed: {e}")
            
            # Execute return if found
            if return_edge_data:
                validation_step = _create_validation_step(G, child_node, current_node, return_edge_data, step_number, f'depth_first_return_{return_method}', tree_id, team_id)
                validation_sequence.append(validation_step)
                visited_edges.add(return_edge)
                print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Step {validation_step['step_number']}: {to_label} → {from_label} (return via {return_method})")
                step_number = validation_step['step_number'] + 1
                current_position = current_node
            else:
                # Strategy 4: No return path available - this is OK for unidirectional actions
                print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] No return path for: {to_label} → {from_label} (unidirectional action - OK)")
        
        recursion_stack.remove(current_node)
    
    # Start depth-first traversal from each entry point
    for entry_point in entry_points:
        depth_first_traversal(entry_point)
    
    # Add any remaining unvisited edges INCLUDING all valid bidirectional edges
    remaining_edges = [(u, v) for u, v in edge_map.keys() if (u, v) not in visited_edges]
    
    print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Found {len(remaining_edges)} remaining unvisited edges")
    
    for edge in remaining_edges:
        from_node, to_node = edge
        

        
        from_info = get_node_info(G, from_node) or {}
        to_info = get_node_info(G, to_node) or {}
        from_label = from_info.get('label', from_node)
        to_label = to_info.get('label', to_node)
        
        # Check if this is a valid edge (has non-empty actions)
        edge_data = edge_map[edge]
        action_sets = edge_data.get('action_sets', [])
        
        # For bidirectional edges, determine which action set to use
        is_bidirectional_return = edge in bidirectional_edges and (to_node, from_node) in visited_edges
        
        has_valid_actions = False
        if is_bidirectional_return:
            # This is a reverse direction - use action set at index 1
            reverse_set = action_sets[1] if len(action_sets) >= 2 else None
            has_valid_actions = reverse_set and reverse_set.get('actions')
        else:
            # This is a forward direction - use action set at index 0
            forward_set = action_sets[0] if action_sets else None
            has_valid_actions = forward_set and forward_set.get('actions')
        
        if has_valid_actions:
            step_type = 'remaining_reverse' if is_bidirectional_return else 'remaining_forward'
            validation_step = _create_validation_step(G, from_node, to_node, edge_data, step_number, step_type, tree_id, team_id)
            validation_sequence.append(validation_step)
            visited_edges.add(edge)
            print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Step {validation_step['step_number']} (remaining): {from_label} → {to_label} ({step_type})")
            step_number = validation_step['step_number'] + 1
        else:
            print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Skipping edge with empty actions: {from_label} → {to_label}")
    
    print(f"[@navigation:pathfinding:_create_reachability_based_validation_sequence] Generated {len(validation_sequence)} validation steps using depth-first traversal")
    
    # Generate clean summary like before refactoring
    print(f"\n🎯 [VALIDATION] CLEAN TRANSITION SUMMARY (like before refactoring)")
    print(f"="*80)
    
    forward_steps = [s for s in validation_sequence if s.get('transition_direction') == 'forward']
    return_steps = [s for s in validation_sequence if s.get('transition_direction') == 'return']
    action_steps = [s for s in validation_sequence if s.get('transition_direction') == 'forward' and get_node_info(G, s['to_node_id']).get('node_type') == 'action']

    print(f"📊 Statistics:")
    print(f"   • Total validation steps: {len(validation_sequence)}")
    print(f"   • Real transitions: {len(forward_steps) + len(return_steps)}")
    print(f"     - Forward: {len(forward_steps)}")
    print(f"     - Return: {len(return_steps)}")
    print(f"     - Action transitions: {len(action_steps)} (included in forward, no position change)")
    print(f"   • All valid edges covered: ✅")

    print(f"\n📋 All Validation Transitions:")
    for i, step in enumerate(validation_sequence, 1):
        from_label = step.get('from_node_label', 'unknown')
        to_label = step.get('to_node_label', 'unknown')
        direction = step.get('transition_direction', 'unknown')

        if direction == 'forward':
            arrow = "→"
            if get_node_info(G, step['to_node_id']).get('node_type') == 'action':
                dir_text = "forward (action)"
            else:
                dir_text = "(forward)"
        elif direction == 'return':
            arrow = "←"
            dir_text = "(return)"
        else:
            arrow = "?"
            dir_text = "(unknown)"

        print(f"   {i:2d}. {from_label} {arrow} {to_label} {dir_text}")
    
    print(f"="*80)
    
    return validation_sequence


def _create_validation_step(G, from_node: str, to_node: str, edge_data: Dict, step_number: int, step_type: str, tree_id: str = None, team_id: str = None) -> Dict:
    """
    Create a validation step for an edge transition.

    Positioning is the runner's responsibility — the validation script repositions
    to ``from_node`` before executing each step (and `NavigationExecutor` clears
    its tracked position on every failure), so this function no longer pre-injects
    forced-transition rows. ``current_position`` was previously consulted to decide
    whether to insert a forced hop; the parameter is now gone.

    Args:
        G: NetworkX graph
        from_node: Source node ID
        to_node: Target node ID
        edge_data: Edge data dictionary
        step_number: Step number in sequence
        step_type: Type of step (depth_first_forward, depth_first_return, remaining)
        tree_id: Tree ID (unused — kept for signature compatibility with future use)
        team_id: Team ID (unused — kept for signature compatibility with future use)
    """
    from shared.src.lib.utils.navigation_graph import get_node_info

    from_info = get_node_info(G, from_node) or {}
    to_info = get_node_info(G, to_node) or {}
    
    # Use standardized 2-action-set structure: forward (index 0) then reverse (index 1)
    action_sets = edge_data.get('action_sets', [])
    
    if not action_sets:
        print(f"[@navigation:pathfinding] Warning: No action sets found for edge {from_node} → {to_node}")
        actions = []
        retry_actions = []
        failure_actions = []
        action_set_used = None
        action_set_used_obj = None
    elif 'return' in step_type and len(action_sets) >= 2:
        # For return steps, use reverse action set (index 1)
        reverse_set = action_sets[1]
        actions = reverse_set.get('actions', [])
        retry_actions = reverse_set.get('retry_actions') or []
        failure_actions = reverse_set.get('failure_actions') or []
        action_set_used = reverse_set['id']
        action_set_used_obj = reverse_set
        print(f"[@navigation:pathfinding] Using reverse action set: {action_set_used}")
    else:
        # For forward steps, use forward action set (index 0)
        forward_set = action_sets[0]
        actions = forward_set.get('actions', [])
        retry_actions = forward_set.get('retry_actions') or []
        failure_actions = forward_set.get('failure_actions') or []
        action_set_used = forward_set['id']
        action_set_used_obj = forward_set
        print(f"[@navigation:pathfinding] Using forward action set: {action_set_used}")
    
    verifications = get_node_info(G, to_node).get('verifications', []) if get_node_info(G, to_node) else []

    # Add cross-tree detection logic
    transition_type = edge_data.get('edge_type', 'NORMAL')
    from_tree_id = from_info.get('tree_id', '')
    to_tree_id = to_info.get('tree_id', '')
    tree_context_change = from_tree_id != to_tree_id

    validation_step = {
        'step_number': step_number,
        'step_type': step_type,
        'from_node_id': from_node,
        'to_node_id': to_node,
        'from_node_label': from_info.get('label', from_node),
        'to_node_label': to_info.get('label', to_node),
        'actions': actions,
        'retryActions': retry_actions,
        'failureActions': failure_actions,
        'action_set_id': action_set_used,  # Track which action set was used
        'original_edge_data': edge_data,  # Pass the original edge with all action sets
        'verifications': verifications,
        'total_actions': len(actions),
        'total_retry_actions': len(retry_actions),
        'total_failure_actions': len(failure_actions),
        'total_verifications': len(verifications),
        # Per-direction final_wait_time on the action_set we picked above.
        'final_wait_time': (action_set_used_obj or {}).get('final_wait_time', 0),
        'edge_id': edge_data.get('edge_id', 'unknown'),
        'transition_direction': 'return' if 'return' in step_type else 'forward',  # Track direction
        'description': f"Validate transition: {from_info.get('label', from_node)} → {to_info.get('label', to_node)}",
        # Add cross-tree metadata
        'transition_type': transition_type,
        'tree_context_change': tree_context_change,
        'from_tree_id': from_tree_id,
        'to_tree_id': to_tree_id  # ✅ ONE TRUTH: target tree (used by executor for DB calls)
    }

    return validation_step