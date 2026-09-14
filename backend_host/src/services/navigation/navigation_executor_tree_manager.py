"""
Navigation Executor Tree Management

Tree loading, hierarchy discovery, and unified data structure building.
Extracted from NavigationExecutor for better maintainability.
"""

from typing import Dict, List, Any, Optional


def load_navigation_tree(
    userinterface_name: str,
    team_id: str,
    unified_graph_storage: Dict = None,
    variant_name: Optional[str] = None,
    ui_mode: str = 'dev',
) -> Dict[str, Any]:
    """
    Load navigation tree and populate unified cache.
    This is the unified function that always works for both simple and nested trees.

    Args:
        userinterface_name: Interface name (e.g., 'example_mobile')
        team_id: Team ID (required)
        unified_graph_storage: Optional dict to store unified_graph for caller
        variant_name: Optional variant name. When provided, this wrapper fetches
            the variant row from `userinterface_variants` and forwards its
            `node_overrides` / `edge_overrides` to `populate_unified_cache`.
            None = base only (only `hidden_in_base` rows are skipped).
        ui_mode: 'dev' (default) or 'prod' — which version of the userinterface
            the name resolves to. A published UI is two rows sharing one name.

    Returns:
        Dictionary with success status and tree data

    Raises:
        NavigationTreeError: If any part of the loading fails
    """
    from shared.src.lib.utils.navigation_exceptions import NavigationTreeError, UnifiedCacheError

    try:
        print(f"🗺️ [TreeManager] Loading navigation tree for '{userinterface_name}' (variant={variant_name})")

        # 1. Get root tree ID to check cache
        from shared.src.lib.database.userinterface_db import (
            get_userinterface_by_name,
            list_variants,
        )
        from shared.src.lib.utils.navigation_graph import (
            parse_variant_list,
            canonical_variant_name,
        )
        userinterface = get_userinterface_by_name(userinterface_name, team_id, mode=ui_mode)
        if not userinterface:
            return {'success': False, 'error': f"User interface '{userinterface_name}' not found (mode={ui_mode})"}

        userinterface_id = userinterface['id']

        # Resolve the variant SELECTION into a canonical composite scope.
        #
        # `variant_name` may name a single variant ('example-v1') OR a composition
        # — a list, or a '+'/','-separated string ('active-standby+no-tvshop').
        # See docs/agent/navigation/VARIANT.md "Composition". We parse it into component
        # names, validate each exists, and collapse to ONE canonical string
        # (sorted, '+'-joined) that is used as the cache key + attribution scope
        # everywhere downstream — so the rest of the stack still treats the
        # variant as a single opaque string.
        #
        # "base" is a UI label for the no-variant graph — parse_variant_list
        # drops literal "base"/""/whitespace, so an env (`DEVICE{i}_VARIANT=base`)
        # or an un-normalized caller collapses to a base run instead of crashing.
        components = parse_variant_list(variant_name)
        canonical_variant = canonical_variant_name(variant_name)  # str | None

        # Fetch every variant of the UI ONCE: gives the applied maps (for
        # composition) AND the full set (to detect legacy "disable-on-others"
        # rows so compose stays backward-compatible without a data migration).
        all_variants = list_variants(team_id, userinterface_id) if components else []
        variants_by_name = {v['name']: v for v in all_variants}

        applied_node_maps: List[Dict] = []
        applied_edge_maps: List[Dict] = []
        cross_disabled_node_ids: set = set()
        cross_disabled_edge_ids: set = set()
        if components:
            missing = [c for c in components if c not in variants_by_name]
            if missing:
                return {
                    'success': False,
                    'error': (
                        f"unknown variant(s) {missing} for userinterface "
                        f"'{userinterface_name}'; available: {sorted(variants_by_name.keys())}"
                    ),
                }
            # Applied maps in CANONICAL (sorted) order so composition is
            # order-independent and 'last wins' is deterministic.
            for name in sorted(components):
                row = variants_by_name[name]
                applied_node_maps.append(row.get('node_overrides') or {})
                applied_edge_maps.append(row.get('edge_overrides') or {})
            # Rows that any variant disables = legacy variant-only rows.
            for v in all_variants:
                for rid, entry in (v.get('node_overrides') or {}).items():
                    if isinstance(entry, dict) and entry.get('disabled'):
                        cross_disabled_node_ids.add(rid)
                for rid, entry in (v.get('edge_overrides') or {}).items():
                    if isinstance(entry, dict) and entry.get('disabled'):
                        cross_disabled_edge_ids.add(rid)

        # Merged override maps are composed in the cache-miss branch (they need
        # the hidden_in_base ids gathered from the full tree hierarchy).
        variant_node_overrides = None
        variant_edge_overrides = None

        # Use the same approach as NavigationEditor - call the working API endpoint
        from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface, get_full_tree
        
        # Get the root tree for this user interface (same as navigation page)
        tree = get_root_tree_for_interface(userinterface_id, team_id)
        
        if not tree:
            return {'success': False, 'error': f"No root tree found for interface: {userinterface_id}"}
        
        root_tree_id = tree['id']
        
        # 2. CHECK CACHE FIRST before loading from database. Cache is keyed per
        #    (tree, team, variant) — each variant gets its own graph because
        #    overrides can fully replace base content (docs/agent/navigation/VARIANT.md).
        from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
        cached_graph = get_cached_unified_graph(root_tree_id, team_id, variant=canonical_variant)
        
        if cached_graph:
            print(f"✅ [TreeManager] Using cached unified graph: {len(cached_graph.nodes)} nodes, {len(cached_graph.edges)} edges")
            if unified_graph_storage is not None:
                unified_graph_storage['graph'] = cached_graph
            
            # Return minimal result - graph is already in memory
            return {
                'success': True,
                'tree_id': root_tree_id,
                'tree': {
                    'id': root_tree_id,
                    'name': tree.get('name', ''),
                },
                'userinterface_id': userinterface_id,
                'from_cache': True,
                'unified_graph_nodes': len(cached_graph.nodes),
                'unified_graph_edges': len(cached_graph.edges)
            }
        
        # 3. CACHE MISS - Load full tree data from database
        print(f"🔄 [TreeManager] Cache miss - loading from database...")
        
        # Get full tree data with nodes and edges (same as navigation page)
        tree_data = get_full_tree(root_tree_id, team_id)
        print(f"[@TreeManager:DEBUG] get_full_tree returned type: {type(tree_data)}")
        print(f"[@TreeManager:DEBUG] get_full_tree keys: {tree_data.keys() if isinstance(tree_data, dict) else 'NOT A DICT'}")
        print(f"[@TreeManager:DEBUG] get_full_tree success: {tree_data.get('success') if isinstance(tree_data, dict) else 'N/A'}")
        
        if not tree_data['success']:
            print(f"[@TreeManager:DEBUG] tree_data['success'] is False, returning error")
            return {'success': False, 'error': f"Failed to load tree data: {tree_data.get('error', 'Unknown error')}"}
        
        print(f"[@TreeManager:DEBUG] Extracting nodes and edges from tree_data")
        nodes = tree_data['nodes']
        edges = tree_data['edges']
        print(f"[@TreeManager:DEBUG] Extracted {len(nodes)} nodes and {len(edges)} edges")
        
        # Create root tree result for hierarchy processing
        root_tree_result = {
            'success': True,
            'tree': {
                'id': root_tree_id,
                'name': tree.get('name', ''),
                'metadata': {
                    'nodes': nodes,
                    'edges': edges
                }
            },
            'tree_id': root_tree_id,
            'userinterface_id': userinterface_id,
            'nodes': nodes,
            'edges': edges
        }
        
        print(f"✅ [TreeManager] Root tree loaded: {root_tree_id}")
        
        # 4. Discover complete tree hierarchy
        print(f"[@TreeManager:DEBUG] Starting discover_complete_hierarchy")
        hierarchy_data = discover_complete_hierarchy(root_tree_id, team_id)
        print(f"[@TreeManager:DEBUG] discover_complete_hierarchy returned: {len(hierarchy_data) if hierarchy_data else 'None'} items")
        if not hierarchy_data:
            # If no nested trees, create single-tree hierarchy
            hierarchy_data = [format_tree_for_hierarchy(root_tree_result, is_root=True)]
            print(f"📋 [TreeManager] No nested trees found, using single root tree")
        else:
            print(f"📋 [TreeManager] Found {len(hierarchy_data)} trees in hierarchy")
        
        # 5. Build unified tree data structure
        print(f"[@TreeManager:DEBUG] Starting build_unified_tree_data")
        all_trees_data = build_unified_tree_data(hierarchy_data, team_id)
        print(f"[@TreeManager:DEBUG] build_unified_tree_data returned: {len(all_trees_data) if all_trees_data else 'None'} items")
        if not all_trees_data:
            raise NavigationTreeError("Failed to build unified tree data structure")
        
        # 5b. Compose the variant overrides now that the full hierarchy is built.
        #     hidden_in_base ids must come from EVERY tree (variant-only rows can
        #     live in subtrees), so they're gathered here, not from the root row.
        if components:
            from shared.src.lib.utils.navigation_graph import (
                compose_node_overrides,
                compose_edge_overrides,
            )
            hidden_node_ids: set = set()
            hidden_edge_ids: set = set()
            for tree_data in all_trees_data:
                for node in tree_data.get('nodes', []):
                    if node.get('hidden_in_base') and node.get('node_id'):
                        hidden_node_ids.add(node['node_id'])
                for edge in tree_data.get('edges', []):
                    if edge.get('hidden_in_base') and edge.get('edge_id'):
                        hidden_edge_ids.add(edge['edge_id'])
            variant_node_overrides = compose_node_overrides(
                applied_node_maps, hidden_node_ids, cross_disabled_node_ids
            )
            variant_edge_overrides = compose_edge_overrides(
                applied_edge_maps, hidden_edge_ids, cross_disabled_edge_ids
            )
            print(
                f"🎭 [TreeManager] Composed variant scope '{canonical_variant}' "
                f"from {len(components)} variant(s): "
                f"{len(variant_node_overrides)} node + {len(variant_edge_overrides)} edge override(s)"
            )

        # 6. Populate unified cache (MANDATORY)
        print(f"🔄 [TreeManager] Populating unified cache...")
        print(f"[@TreeManager:DEBUG] Calling populate_unified_cache (variant={canonical_variant})")
        from shared.src.lib.utils.navigation_cache import populate_unified_cache
        unified_graph = populate_unified_cache(
            root_tree_id,
            team_id,
            all_trees_data,
            variant_node_overrides=variant_node_overrides,
            variant_edge_overrides=variant_edge_overrides,
            variant=canonical_variant,
        )
        print(f"[@TreeManager:DEBUG] populate_unified_cache returned: {unified_graph is not None}")
        if not unified_graph:
            raise UnifiedCacheError("Failed to populate unified cache - navigation will not work")
        
        print(f"✅ [TreeManager] Unified cache populated: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")
        
        # Store unified graph for caller if storage provided
        if unified_graph_storage is not None:
            unified_graph_storage['graph'] = unified_graph
        
        # 7. Return result compatible with script executor expectations
        result = {
            'success': True,
            'tree_id': root_tree_id,
            'tree': {
                'id': root_tree_id,
                'name': tree.get('name', ''),
                'metadata': {
                    'nodes': nodes,
                    'edges': edges
                }
            },
            'userinterface_id': userinterface_id,
            'nodes': nodes,
            'edges': edges,
            'from_cache': False,
            # Additional hierarchy info for advanced use cases
            'hierarchy': hierarchy_data,
            'unified_graph_nodes': len(unified_graph.nodes),
            'unified_graph_edges': len(unified_graph.edges),
            'cross_tree_capabilities': len(hierarchy_data) > 1
        }
        print(f"[@TreeManager:DEBUG] ✅ Returning success result with {len(nodes)} nodes and {len(edges)} edges")
        return result
        
    except Exception as e:
        # Re-raise navigation-specific errors
        print(f"[@TreeManager:DEBUG] ❌ Exception caught in load_navigation_tree")
        print(f"[@TreeManager:DEBUG] Exception type: {type(e).__name__}")
        print(f"[@TreeManager:DEBUG] Exception message: {str(e)}")
        import traceback
        print(f"[@TreeManager:DEBUG] Traceback:\n{traceback.format_exc()}")
        
        from shared.src.lib.utils.navigation_exceptions import NavigationTreeError, UnifiedCacheError
        if isinstance(e, (NavigationTreeError, UnifiedCacheError)):
            print(f"[@TreeManager:DEBUG] Re-raising navigation-specific error")
            raise e
        else:
            # FAIL EARLY - no fallback
            print(f"[@TreeManager:DEBUG] Returning error dict")
            return {'success': False, 'error': f"Navigation tree loading failed: {str(e)}"}


def discover_complete_hierarchy(root_tree_id: str, team_id: str) -> List[Dict]:
    """
    Discover all nested trees in hierarchy using enhanced database functions.
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        
    Returns:
        List of tree data dictionaries for the complete hierarchy
    """
    try:
        from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy
        
        print(f"🔍 [TreeManager] Discovering complete tree hierarchy using enhanced database function...")
        
        # Use the new enhanced database function
        hierarchy_result = get_complete_tree_hierarchy(root_tree_id, team_id)
        if not hierarchy_result['success']:
            print(f"⚠️ [TreeManager] Failed to get complete hierarchy: {hierarchy_result.get('error', 'Unknown error')}")
            return []
        
        hierarchy_data = hierarchy_result['hierarchy']
        if not hierarchy_data:
            print(f"📋 [TreeManager] Empty hierarchy returned from database")
            return []
        
        total_trees = hierarchy_result.get('total_trees', len(hierarchy_data))
        max_depth = hierarchy_result.get('max_depth', 0)
        has_nested = hierarchy_result.get('has_nested_trees', False)
        
        print(f"✅ [TreeManager] Complete hierarchy discovered:")
        print(f"   • Total trees: {total_trees}")
        print(f"   • Maximum depth: {max_depth}")
        print(f"   • Has nested trees: {has_nested}")
        
        # The data is already in the correct format from the database function
        return hierarchy_data
        
    except Exception as e:
        print(f"❌ [TreeManager] Error discovering hierarchy: {str(e)}")
        return []


def format_tree_for_hierarchy(tree_data: Dict, tree_info: Dict = None, is_root: bool = False) -> Dict:
    """
    Format tree data for unified hierarchy structure.
    
    Args:
        tree_data: Tree data from database
        tree_info: Optional hierarchy metadata
        is_root: Whether this is the root tree
        
    Returns:
        Formatted tree data for unified processing
    """
    if is_root:
        # Root tree from load_navigation_tree
        return {
            'tree_id': tree_data['tree_id'],
            'tree_info': {
                'name': tree_data['tree']['name'],
                'is_root_tree': True,
                'tree_depth': 0,
                'parent_tree_id': None,
                'parent_node_id': None
            },
            'nodes': tree_data['nodes'],
            'edges': tree_data['edges']
        }
    else:
        # Nested tree from hierarchy
        return {
            'tree_id': tree_info['tree_id'],
            'tree_info': {
                'name': tree_info.get('tree_name', ''),
                'is_root_tree': tree_info.get('depth', 0) == 0,
                'tree_depth': tree_info.get('depth', 0),
                'parent_tree_id': tree_info.get('parent_tree_id'),
                'parent_node_id': tree_info.get('parent_node_id')
            },
            'nodes': tree_data['nodes'],
            'edges': tree_data['edges']
        }


def build_unified_tree_data(hierarchy_data: List[Dict], team_id: str) -> List[Dict]:
    """
    Build unified data structure for cache population.
    
    Args:
        hierarchy_data: List of formatted tree data
        team_id: Team ID for fetching any missing subtrees referenced by nodes
        
    Returns:
        Data structure ready for create_unified_networkx_graph()
    """
    from shared.src.lib.utils.navigation_exceptions import NavigationTreeError
    
    try:
        if not hierarchy_data:
            print(f"⚠️ [TreeManager] No hierarchy data to build unified structure")
            return []
        
        print(f"🔧 [TreeManager] Building unified data structure from {len(hierarchy_data)} trees")
        
        # The hierarchy_data is already in the correct format for create_unified_networkx_graph
        # Validate first
        for tree_data in hierarchy_data:
            required_keys = ['tree_id', 'tree_info', 'nodes', 'edges']
            for key in required_keys:
                if key not in tree_data:
                    raise NavigationTreeError(f"Missing required key '{key}' in tree data")

        # Augment: ensure all child trees referenced by nodes are included
        # Build quick lookup and queue for BFS across child_tree_id references
        trees_by_id: Dict[str, Dict] = {t['tree_id']: t for t in hierarchy_data}
        initial_tree_ids = list(trees_by_id.keys())

        added_count = 0
        from shared.src.lib.database.navigation_trees_db import get_full_tree

        # For each known tree, scan nodes for child_tree_id references and add missing trees
        scan_queue = initial_tree_ids.copy()
        while scan_queue:
            current_tree_id = scan_queue.pop(0)
            current_tree = trees_by_id[current_tree_id]
            current_depth = current_tree.get('tree_info', {}).get('tree_depth', 0)

            for node in current_tree.get('nodes', []):
                # child_tree_id may be directly on node or inside node['data'] depending on DB format
                node_data = node.get('data', {}) if isinstance(node.get('data'), dict) else {}
                child_tree_id = node.get('child_tree_id') or node_data.get('child_tree_id')
                if not child_tree_id or child_tree_id in trees_by_id:
                    continue

                # Fetch full data for the missing child tree
                child_full = get_full_tree(child_tree_id, team_id)
                if not child_full.get('success'):
                    print(f"⚠️ [TreeManager] Failed to load child tree '{child_tree_id}' referenced by node '{node.get('node_id')}'")
                    continue

                # Compose tree_info linking back to the parent node
                child_tree_info = {
                    'name': child_full['tree'].get('name', ''),
                    'is_root_tree': False,
                    'tree_depth': current_depth + 1,
                    'parent_tree_id': current_tree_id,
                    'parent_node_id': node.get('node_id')
                }

                trees_by_id[child_tree_id] = {
                    'tree_id': child_tree_id,
                    'tree_info': child_tree_info,
                    'nodes': child_full.get('nodes', []),
                    'edges': child_full.get('edges', [])
                }
                scan_queue.append(child_tree_id)
                added_count += 1

        if added_count:
            print(f"✅ [TreeManager] Augmented hierarchy with {added_count} child trees discovered via node references")

        unified_list = list(trees_by_id.values())
        print(f"✅ [TreeManager] Unified data structure validated (total trees: {len(unified_list)})")
        return unified_list
        
    except Exception as e:
        print(f"❌ [TreeManager] Error building unified data: {str(e)}")
        return []

