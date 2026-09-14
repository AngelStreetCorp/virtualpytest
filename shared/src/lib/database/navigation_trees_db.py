"""
Navigation Trees Database Operations - Normalized Architecture

This module provides functions for managing navigation trees using the new normalized structure:
- navigation_trees: Tree metadata containers with nested tree support
- navigation_nodes: Individual nodes with embedded verifications
- navigation_edges: Edges with embedded actions

Clean, scalable, individual record operations with nested tree functionality.
"""

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set
from uuid import UUID, uuid4

from shared.src.lib.utils.supabase_utils import get_supabase_client

def get_supabase():
    """Get the Supabase client instance."""
    return get_supabase_client()

# System rows every interface gets from create_default_navigation_tree() (see
# setup/db/schema/002_ui_navigation_tables.sql) — keep in sync with it.
# Import/duplicate drop that trigger-seeded tree and write the hierarchy
# themselves, and mv_full_navigation_trees does not expose is_system_protected,
# so the copied rows carry no flag and must have the invariant re-applied.
# The node delete trigger also refuses these node_ids by name in ANY tree, so
# the flag is applied per row id, not only on the root tree.
PROTECTED_NODE_IDS = frozenset({'entry-node', 'home'})
PROTECTED_EDGE_IDS = frozenset({'edge-entry-node-to-home'})

def _get_root_tree_id(tree_id: str, team_id: str) -> Optional[str]:
    """
    Get root tree ID for a given tree (could be a subtree)
    
    Args:
        tree_id: Current tree ID (may be a subtree)
        team_id: Team ID
        
    Returns:
        Root tree ID or None
    """
    try:
        supabase = get_supabase()
        
        # Get tree info
        tree_result = supabase.table('navigation_trees').select('id, is_root_tree, parent_tree_id, userinterface_id')\
            .eq('id', tree_id)\
            .eq('team_id', team_id)\
            .limit(1)\
            .execute()
        
        if not tree_result.data:
            return None
        
        tree_info = tree_result.data[0]
        
        # If already root, return it
        if tree_info.get('is_root_tree'):
            return tree_id
        
        # If has parent_tree_id, traverse up
        if tree_info.get('parent_tree_id'):
            return _get_root_tree_id(tree_info['parent_tree_id'], team_id)
        
        # Fallback: Find root by userinterface_id
        if tree_info.get('userinterface_id'):
            root_result = supabase.table('navigation_trees').select('id')\
                .eq('userinterface_id', tree_info['userinterface_id'])\
                .eq('team_id', team_id)\
                .eq('is_root_tree', True)\
                .limit(1)\
                .execute()
            
            if root_result.data:
                return root_result.data[0]['id']
        
        return None
        
    except Exception as e:
        print(f"[@db:_get_root_tree_id] Error: {e}")
        return None

def invalidate_navigation_cache_for_tree(tree_id: str, team_id: str):
    """
    Clear cache when tree is modified (on ANY save: edge, node, tree)
    Cache will be rebuilt automatically on next navigation/take-control
    
    SIMPLE: Just clear local cache (works for direct HOST usage)
    """
    try:
        print(f"[@cache_invalidation] 🔄 Clearing LOCAL cache for tree: {tree_id} (will rebuild on next take-control)")
        
        # Clear local cache directly (works when running in backend_host)
        from shared.src.lib.utils.navigation_cache import clear_unified_cache
        clear_unified_cache(tree_id, team_id)
        
        print(f"[@cache_invalidation] ✅ Cache cleared for tree: {tree_id}")
        
        # NOTE: Materialized view (mv_full_navigation_trees) is automatically refreshed by database triggers
        # on navigation_nodes, navigation_edges, and navigation_trees tables - no manual refresh needed
    except Exception as e:
        print(f"[@cache_invalidation] Error: {e}")
        import traceback
        traceback.print_exc()

# ============================================================================
# TREE METADATA OPERATIONS
# ============================================================================

def get_all_trees(team_id: str) -> Dict:
    """Get all navigation trees metadata for a team."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees').select('*').eq('team_id', team_id).order('created_at').execute()
        
        print(f"[@db:navigation_trees:get_all_trees] Retrieved {len(result.data)} trees")
        return {'success': True, 'trees': result.data}
    except Exception as e:
        print(f"[@db:navigation_trees:get_all_trees] Error: {e}")
        return {'success': False, 'error': str(e), 'trees': []}

def get_tree_metadata(tree_id: str, team_id: str) -> Dict:
    """Get tree basic information."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees').select('*').eq('id', tree_id).eq('team_id', team_id).execute()
        
        if result.data:
            return {'success': True, 'tree': result.data[0]}
        else:
            return {'success': False, 'error': 'Tree not found'}
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_metadata] Error: {e}")
        return {'success': False, 'error': str(e)}

def save_tree_metadata(tree_data: Dict, team_id: str) -> Dict:
    """Save tree metadata (create or update)."""
    try:
        supabase = get_supabase()
        tree_data['team_id'] = team_id
        tree_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        if 'id' in tree_data and tree_data['id']:
            # Update existing tree
            result = supabase.table('navigation_trees').update(tree_data).eq('id', tree_data['id']).eq('team_id', team_id).execute()
            print(f"[@db:navigation_trees:save_tree_metadata] Updated tree: {tree_data['id']}")
        else:
            # Create new tree
            tree_data['id'] = str(uuid4())
            tree_data['created_at'] = datetime.now(timezone.utc).isoformat()
            result = supabase.table('navigation_trees').insert(tree_data).execute()
            print(f"[@db:navigation_trees:save_tree_metadata] Created new tree: {tree_data['id']}")
        
        return {'success': True, 'tree': result.data[0]}
    except Exception as e:
        print(f"[@db:navigation_trees:save_tree_metadata] Error: {e}")
        return {'success': False, 'error': str(e)}

def delete_tree(tree_id: str, team_id: str) -> Dict:
    """Delete a tree (cascade will handle nodes and edges)."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees').delete().eq('id', tree_id).eq('team_id', team_id).execute()
        
        print(f"[@db:navigation_trees:delete_tree] Deleted tree: {tree_id}")
        return {'success': True}
    except Exception as e:
        print(f"[@db:navigation_trees:delete_tree] Error: {e}")
        return {'success': False, 'error': str(e)}

def save_tree_hierarchy(all_trees_data: List[Dict], target_userinterface_id: str, target_userinterface_name: str, team_id: str, record_source_ids: bool = False) -> Dict:
    """Insert a full tree hierarchy (root + all subtrees) under a target userinterface.

    Shared writer for both duplicate (source = live DB via get_complete_tree_hierarchy)
    and import (source = a .vptree bundle). Each element of `all_trees_data` is the
    get_complete_tree_hierarchy shape:
        {tree_id, tree_info:{name,is_root_tree,tree_depth,parent_tree_id,parent_node_id}, nodes[], edges[]}

    record_source_ids: when True (dev->prod first publish), each inserted tree
    stamps published_from_tree_id = its source tree id at insert time — one
    statement, no follow-up UPDATEs (every navigation_* statement fires a full
    MV refresh). Republish uses that mapping to sync in place.

    Every tree gets a fresh UUID; `parent_tree_id` is remapped old->new via the running
    mapping (trees are inserted depth-first so a parent always exists before its child).
    `parent_node_id` and every node_id/edge_id are copied verbatim (they are only unique
    within a tree, so they stay stable). Node/edge payloads (data/style/verifications/
    action_sets) are copied as-is — no URL rewriting happens here; callers that move
    objects between stores handle references separately.

    Returns {success, tree_id_mapping (old->new), root_tree_id (new id of the is_root_tree
    tree), trees_count, nodes_count, edges_count}.
    """
    try:
        supabase = get_supabase()
        timestamp = datetime.now(timezone.utc).isoformat()

        tree_id_mapping = {}
        total_nodes = 0
        total_edges = 0
        root_old_id = None

        # Process trees in depth order (root first) so each parent exists before its child.
        for tree_data in sorted(all_trees_data, key=lambda x: x['tree_info']['tree_depth']):
            old_tree_id = tree_data['tree_id']
            tree_info = tree_data['tree_info']
            if tree_info.get('is_root_tree'):
                root_old_id = old_tree_id

            new_tree_id = str(uuid4())
            tree_id_mapping[old_tree_id] = new_tree_id

            # Determine parent relationships for the new tree
            parent_tree_id = None
            parent_node_id = None
            if tree_info.get('parent_tree_id'):
                # Map old parent tree ID to new parent tree ID
                parent_tree_id = tree_id_mapping.get(tree_info['parent_tree_id'])
                parent_node_id = tree_info.get('parent_node_id')  # Node IDs stay the same within trees

            # Insert new tree record
            tree_row = {
                'id': new_tree_id,
                'name': tree_info.get('name', f"{target_userinterface_name}_tree"),
                'userinterface_id': target_userinterface_id,
                'is_root_tree': tree_info.get('is_root_tree', False),
                'tree_depth': tree_info.get('tree_depth', 0),
                'parent_tree_id': parent_tree_id,
                'parent_node_id': parent_node_id,
                'viewport_x': tree_data.get('tree', {}).get('viewport_x', 0),
                'viewport_y': tree_data.get('tree', {}).get('viewport_y', 0),
                'viewport_zoom': tree_data.get('tree', {}).get('viewport_zoom', 1),
                'team_id': team_id,
                'created_at': timestamp,
                'updated_at': timestamp
            }
            if record_source_ids:
                tree_row['published_from_tree_id'] = old_tree_id
            supabase.table('navigation_trees').insert(tree_row).execute()

            # Batch insert nodes for this tree
            if tree_data.get('nodes'):
                nodes = [{
                    'tree_id': new_tree_id,
                    'node_id': n['node_id'],
                    'label': n.get('label', ''),
                    'node_type': n.get('node_type', 'screen'),
                    'position_x': n.get('position_x', 0),
                    'position_y': n.get('position_y', 0),
                    'data': n.get('data', {}),
                    'style': n.get('style', {}),
                    'verifications': n.get('verifications', []),
                    'hidden_in_base': n.get('hidden_in_base', False),
                    # protection is a floor: never lower what the source claims
                    'is_system_protected': bool(n.get('is_system_protected'))
                                           or n['node_id'] in PROTECTED_NODE_IDS,
                    'team_id': team_id,
                    'created_at': timestamp,
                    'updated_at': timestamp
                } for n in tree_data['nodes']]
                supabase.table('navigation_nodes').insert(nodes).execute()
                total_nodes += len(nodes)

            # Batch insert edges for this tree
            if tree_data.get('edges'):
                edges = [{
                    'tree_id': new_tree_id,
                    'edge_id': e['edge_id'],
                    'source_node_id': e['source_node_id'],
                    'target_node_id': e['target_node_id'],
                    # final_wait_time + threshold live per-direction inside action_sets.
                    'action_sets': e.get('action_sets', []),
                    'default_action_set_id': e.get('default_action_set_id', ''),
                    'label': e.get('label', ''),
                    'data': e.get('data', {}),
                    'hidden_in_base': e.get('hidden_in_base', False),
                    # protection is a floor: never lower what the source claims
                    'is_system_protected': bool(e.get('is_system_protected'))
                                           or e['edge_id'] in PROTECTED_EDGE_IDS,
                    'team_id': team_id,
                    'created_at': timestamp,
                    'updated_at': timestamp
                } for e in tree_data['edges']]
                supabase.table('navigation_edges').insert(edges).execute()
                total_edges += len(edges)

            print(f"[@db:navigation_trees:save_tree_hierarchy] Inserted tree {old_tree_id} -> {new_tree_id} ({len(tree_data.get('nodes', []))} nodes, {len(tree_data.get('edges', []))} edges)")

        # Invalidate caches for all new trees
        for new_tree_id in tree_id_mapping.values():
            invalidate_navigation_cache_for_tree(new_tree_id, team_id)

        # Root = the is_root_tree tree, falling back to the shallowest one.
        if root_old_id is None and all_trees_data:
            root_old_id = min(all_trees_data, key=lambda x: x['tree_info']['tree_depth'])['tree_id']

        print(f"[@db:navigation_trees:save_tree_hierarchy] Complete hierarchy saved: {len(tree_id_mapping)} trees, {total_nodes} total nodes, {total_edges} total edges")

        return {
            'success': True,
            'tree_id_mapping': tree_id_mapping,
            'root_tree_id': tree_id_mapping.get(root_old_id),
            'trees_count': len(tree_id_mapping),
            'nodes_count': total_nodes,
            'edges_count': total_edges
        }

    except Exception as e:
        print(f"[@db:navigation_trees:save_tree_hierarchy] Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def duplicate_tree_hierarchy(source_tree_id: str, target_userinterface_id: str, target_userinterface_name: str, team_id: str, record_source_ids: bool = False) -> Dict:
    """
    Recursively duplicate entire navigation tree hierarchy including all subtrees.

    Reads the source hierarchy from the live DB, then delegates the actual writing to
    save_tree_hierarchy (shared with the .vptree import path).
    """
    try:
        # Get complete tree hierarchy (root + all descendant trees)
        hierarchy_result = get_complete_tree_hierarchy(source_tree_id, team_id)
        if not hierarchy_result['success']:
            return {'success': False, 'error': f"Failed to get tree hierarchy: {hierarchy_result.get('error')}"}

        result = save_tree_hierarchy(
            hierarchy_result['all_trees_data'], target_userinterface_id, target_userinterface_name, team_id,
            record_source_ids=record_source_ids)
        if not result.get('success'):
            return result

        # Preserve the legacy return contract: `tree_id` is the new root tree id
        # (mapped from the original source_tree_id when it is the root).
        return {
            'success': True,
            'tree_id': result['tree_id_mapping'].get(source_tree_id) or result['root_tree_id'],
            'trees_count': result['trees_count'],
            'nodes_count': result['nodes_count'],
            'edges_count': result['edges_count']
        }

    except Exception as e:
        print(f"[@db:navigation_trees:duplicate_tree_hierarchy] Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}


def duplicate_tree(source_tree_id: str, target_userinterface_id: str, target_userinterface_name: str, team_id: str) -> Dict:
    """
    Legacy function - now delegates to duplicate_tree_hierarchy for full subtree support.

    Duplicate entire navigation tree (optimized with batch inserts).
    """
    print(f"[@db:navigation_trees:duplicate_tree] Using new hierarchy-aware duplication for tree: {source_tree_id}")
    return duplicate_tree_hierarchy(source_tree_id, target_userinterface_id, target_userinterface_name, team_id)

def get_root_tree_for_interface(userinterface_id: str, team_id: str) -> Optional[Dict]:
    """Get the root tree for a specific user interface."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees').select('*')\
            .eq('userinterface_id', userinterface_id)\
            .eq('team_id', team_id)\
            .eq('is_root_tree', True)\
            .order('created_at')\
            .limit(1)\
            .execute()
        
        if result.data:
            print(f"[@db:navigation_trees:get_root_tree_for_interface] Found root tree for interface: {userinterface_id}")
            return result.data[0]
        else:
            print(f"[@db:navigation_trees:get_root_tree_for_interface] No root tree found for interface: {userinterface_id}")
            return None
    except Exception as e:
        print(f"[@db:navigation_trees:get_root_tree_for_interface] Error: {e}")
        return None

# ============================================================================
# NODE OPERATIONS
# ============================================================================

def get_root_trees_for_interfaces(userinterface_ids: List[str], team_id: str) -> Dict[str, Dict]:
    """{userinterface_id: root_tree} for many interfaces in ONE round trip.

    Batched counterpart of get_root_tree_for_interface, and matches its
    tie-break: when an interface has several root trees the oldest wins.
    """
    if not userinterface_ids:
        return {}
    try:
        supabase = get_supabase()
        out: Dict[str, Dict] = {}
        CHUNK = 100
        for i in range(0, len(userinterface_ids), CHUNK):
            result = supabase.table('navigation_trees').select('*')\
                .in_('userinterface_id', userinterface_ids[i:i + CHUNK])\
                .eq('team_id', team_id)\
                .eq('is_root_tree', True)\
                .order('created_at')\
                .execute()
            for row in (result.data or []):
                # rows come back created_at-ascending, so the first one seen
                # for an interface is the oldest — same pick as the single-id fn
                out.setdefault(row['userinterface_id'], row)
        return out
    except Exception as e:
        print(f"[@db:navigation_trees:get_root_trees_for_interfaces] Error: {e}")
        return {}

def get_tree_ids_with_nodes(tree_ids: List[str], team_id: str) -> Set[str]:
    """Which of these trees have at least one node — in ONE round trip.

    Callers only need the boolean, so select just tree_id: one small column per
    node row instead of full rows.
    """
    if not tree_ids:
        return set()
    try:
        supabase = get_supabase()
        found: Set[str] = set()
        CHUNK = 100
        for i in range(0, len(tree_ids), CHUNK):
            result = supabase.table('navigation_nodes').select('tree_id')\
                .in_('tree_id', tree_ids[i:i + CHUNK])\
                .eq('team_id', team_id)\
                .execute()
            for row in (result.data or []):
                found.add(row['tree_id'])
        return found
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_ids_with_nodes] Error: {e}")
        return set()

def get_tree_nodes(tree_id: str, team_id: str, page: int = 0, limit: int = 100) -> Dict:
    """Get nodes for a tree with pagination."""
    try:
        supabase = get_supabase()
        offset = page * limit
        
        result = supabase.table('navigation_nodes').select('*')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .range(offset, offset + limit - 1)\
            .order('created_at')\
            .execute()
        
        return {'success': True, 'nodes': result.data}
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_nodes] Error: {e}")
        return {'success': False, 'error': str(e)}

def get_node_display_name(root_tree_id: str, team_id: str, node_label: str) -> str:
    """Return a node's friendly display name (data.display_name) by label, or ''.

    Nodes can live in sub-trees, so this walks the COMPLETE hierarchy from the
    root tree (same source as the RunTests node picker) rather than a single
    tree. Returns '' when the node has no display name or can't be found — callers
    fall back to the raw label. Shared by standby_measurement / zap_chup so the
    resolution logic lives in one place.
    """
    if not node_label:
        return ''
    try:
        hierarchy = get_complete_tree_hierarchy(root_tree_id, team_id)
        if not hierarchy.get('success'):
            return ''
        for tree in hierarchy.get('all_trees_data', []):
            for node in tree.get('nodes', []):
                if (node.get('label') or '') == node_label:
                    data = node.get('data') if isinstance(node.get('data'), dict) else {}
                    return (data.get('display_name') or '').strip()
    except Exception as e:
        print(f"[@db:navigation_trees:get_node_display_name] Error: {e}")
    return ''


def get_node_by_id(tree_id: str, node_id: str, team_id: str) -> Dict:
    """Get a single node by its node_id."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_nodes').select('*')\
            .eq('tree_id', tree_id)\
            .eq('node_id', node_id)\
            .eq('team_id', team_id)\
            .execute()

        if result.data:
            print(f"[@db:navigation_trees:get_node_by_id] Retrieved node: {node_id}")
            return {'success': True, 'node': result.data[0]}
        else:
            print(f"[@db:navigation_trees:get_node_by_id] Node not found: {node_id}")
            return {'success': False, 'error': 'Node not found'}
    except Exception as e:
        print(f"[@db:navigation_trees:get_node_by_id] Error: {e}")
        return {'success': False, 'error': str(e)}


def resolve_node(tree_id: str, identifier: str, team_id: str, prefer_id: bool = True) -> Dict:
    """
    Robustly resolve a node by either node_id or label.

    First tries exact match by the preferred field, then falls back to the other field.
    Returns the resolved node and indicates which field was used for matching.

    Args:
        tree_id: Navigation tree ID
        identifier: Either node_id or label to search for
        team_id: Team ID for security
        prefer_id: If True, try node_id field first, then label. If False, try label first, then node_id.

    Returns:
        {
            'success': bool,
            'node': dict or None,
            'resolution_method': 'exact_node_id' | 'exact_label' | 'fallback_node_id' | 'fallback_label' | None,
            'error': str or None
        }
    """
    try:
        supabase = get_supabase()

        # Get all nodes in the tree (we need to search across both fields)
        result = supabase.table('navigation_nodes').select('*')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .execute()

        if not result.data:
            return {'success': False, 'error': 'No nodes found in tree', 'resolution_method': None}

        nodes = result.data
        matching_node = None
        resolution_method = None

        # Step 1: Try exact match by preferred field
        if prefer_id:
            # Prefer node_id field first
            for node in nodes:
                if node.get('node_id') == identifier:
                    matching_node = node
                    resolution_method = 'exact_node_id'
                    break
        else:
            # Prefer label field first
            for node in nodes:
                if node.get('label') == identifier:
                    matching_node = node
                    resolution_method = 'exact_label'
                    break

        # Step 2: If no exact match, try fallback in the other field
        if not matching_node:
            if prefer_id:
                # Fallback: search by label field
                for node in nodes:
                    if node.get('label') == identifier:
                        matching_node = node
                        resolution_method = 'fallback_label'
                        break
            else:
                # Fallback: search by node_id field
                for node in nodes:
                    if node.get('node_id') == identifier:
                        matching_node = node
                        resolution_method = 'fallback_node_id'
                        break

        if matching_node:
            print(f"[@db:navigation_trees:resolve_node] {resolution_method}: '{identifier}' → node_id: {matching_node.get('node_id')}")
            return {
                'success': True,
                'node': matching_node,
                'resolution_method': resolution_method
            }
        else:
            available_identifiers = [node.get('label', node.get('node_id', 'unknown')) for node in nodes[:10]]
            print(f"[@db:navigation_trees:resolve_node] Node '{identifier}' not found")
            return {
                'success': False,
                'error': f"Node '{identifier}' not found. Available: {', '.join(available_identifiers)}",
                'resolution_method': None
            }

    except Exception as e:
        print(f"[@db:navigation_trees:resolve_node] Error: {e}")
        return {'success': False, 'error': str(e), 'resolution_method': None}

def get_nodes_batch(tree_id: str, node_ids: list, team_id: str) -> Dict:
    """Get multiple nodes by their node_ids in a single query (optimized for N+1 prevention)."""
    try:
        if not node_ids:
            return {'success': True, 'nodes': {}}
        
        supabase = get_supabase()
        result = supabase.table('navigation_nodes').select('*')\
            .eq('tree_id', tree_id)\
            .in_('node_id', node_ids)\
            .eq('team_id', team_id)\
            .execute()
        
        # Create a dict for fast lookup: node_id -> node_data
        nodes_dict = {node['node_id']: node for node in result.data} if result.data else {}
        
        print(f"[@db:navigation_trees:get_nodes_batch] Retrieved {len(nodes_dict)}/{len(node_ids)} nodes in single query")
        return {'success': True, 'nodes': nodes_dict}
    except Exception as e:
        print(f"[@db:navigation_trees:get_nodes_batch] Error: {e}")
        return {'success': False, 'error': str(e)}

def save_node(tree_id: str, node_data: Dict, team_id: str) -> Dict:
    """Save a single node (create or update)."""
    try:
        supabase = get_supabase()
        node_data['tree_id'] = tree_id
        node_data['team_id'] = team_id
        node_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Ensure data field is never null - database constraint requires it
        if 'data' not in node_data or node_data['data'] is None:
            node_data['data'] = {}
        
        # Sync data.type with node_type for frontend compatibility
        if 'node_type' in node_data:
            node_data['data']['type'] = node_data['node_type']
        
        # 🛡️ PROTECTION: Auto-migrate verifications from data.verifications to root level
        # This protects against AI/API misuse where verifications are put in wrong location
        if 'data' in node_data and 'verifications' in node_data.get('data', {}):
            data_verifications = node_data['data']['verifications']
            
            # If root verifications is empty or missing, migrate from data
            if not node_data.get('verifications'):
                node_data['verifications'] = data_verifications
                print(f"[@db:save_node] ⚠️ Auto-migrated {len(data_verifications)} verifications from data.verifications to root level for node {node_data.get('node_id')}")
            
            # Always clean up the duplicate to avoid confusion
            if data_verifications:
                del node_data['data']['verifications']
                print(f"[@db:save_node] 🧹 Removed duplicate verifications from data.verifications")
        
        # 🛡️ PROTECTION: Normalize verification structure (ensure 'command' exists, not just 'method')
        if 'verifications' in node_data and isinstance(node_data['verifications'], list):
            normalized_verifications = []
            for v in node_data['verifications']:
                if isinstance(v, dict):
                    # If 'method' exists but 'command' doesn't, migrate it
                    if 'method' in v and 'command' not in v:
                        v['command'] = v['method']
                        print(f"[@db:save_node] 🔧 Auto-migrated verification: 'method' → 'command' = '{v['command']}'")
                    
                    # Ensure 'command' is not empty
                    if not v.get('command') or v.get('command', '').strip() == '':
                        print(f"[@db:save_node] ⚠️ Skipping verification with missing/empty command")
                        continue
                    
                    normalized_verifications.append(v)
            
            node_data['verifications'] = normalized_verifications
        
        # Log what we're about to save
        print(f"[@db:navigation_trees:save_node] Saving node {node_data['node_id']}")
        print(f"[@db:navigation_trees:save_node] data.is_root = {node_data.get('data', {}).get('is_root')}")
        print(f"[@db:navigation_trees:save_node] Full data field: {node_data.get('data')}")
        
        # Ensure style field is never null - database constraint requires it
        if 'style' not in node_data or node_data['style'] is None:
            node_data['style'] = {}
        
        # Check if node exists
        existing = supabase.table('navigation_nodes').select('id')\
            .eq('tree_id', tree_id)\
            .eq('node_id', node_data['node_id'])\
            .eq('team_id', team_id)\
            .execute()
        
        if existing.data:
            # Update existing node
            result = supabase.table('navigation_nodes').update(node_data)\
                .eq('tree_id', tree_id)\
                .eq('node_id', node_data['node_id'])\
                .eq('team_id', team_id)\
            .execute()
            print(f"[@db:navigation_trees:save_node] Updated node: {node_data['node_id']}, position: ({node_data.get('position_x', 'missing')}, {node_data.get('position_y', 'missing')})")
        else:
            # Insert new node
            node_data['created_at'] = datetime.now(timezone.utc).isoformat()
            result = supabase.table('navigation_nodes').insert(node_data).execute()
            print(f"[@db:navigation_trees:save_node] Created new node: {node_data['node_id']}, position: ({node_data.get('position_x', 'missing')}, {node_data.get('position_y', 'missing')})")
        
        # NOTE: Cache updates are handled by frontend calling /server/navigation/cache/update-node
        # which proxies to all hosts for incremental NetworkX graph updates (graph.nodes[id].update())
        # This is O(1) incremental update - no full graph rebuild needed
        
        return {'success': True, 'node': result.data[0]}
    except Exception as e:
        print(f"[@db:navigation_trees:save_node] Error: {e}")
        return {'success': False, 'error': str(e)}

def save_nodes_batch(tree_id: str, nodes_data: List[Dict], team_id: str) -> Dict:
    """
    Save multiple nodes in a single transaction (upsert).
    
    BENEFITS:
    1. Efficiency: 1 Network request vs N requests
    2. Trigger Control: Database trigger (FOR EACH STATEMENT) fires ONLY ONCE per batch,
       preventing "refresh storm" on materialized view which causes race conditions.
    
    Normalizes data (style, data structure) just like single save_node.
    """
    try:
        supabase = get_supabase()
        
        processed_nodes = []
        
        for node_data in nodes_data:
            # Prepare fields
            node_data['tree_id'] = tree_id
            node_data['team_id'] = team_id
            node_data['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Handle 'created_at' for new nodes
            # Note: upsert will ignore this for updates if configured, but we send it just in case
            if 'created_at' not in node_data:
                 node_data['created_at'] = datetime.now(timezone.utc).isoformat()

            # Ensure data field is never null
            if 'data' not in node_data or node_data['data'] is None:
                node_data['data'] = {}
            
            # Sync data.type with node_type
            if 'node_type' in node_data:
                node_data['data']['type'] = node_data['node_type']
            
            # 🛡️ PROTECTION: Auto-migrate verifications
            if 'data' in node_data and 'verifications' in node_data.get('data', {}):
                data_verifications = node_data['data']['verifications']
                if not node_data.get('verifications'):
                    node_data['verifications'] = data_verifications
                    print(f"[@db:save_nodes_batch] ⚠️ Auto-migrated verifications for node {node_data.get('node_id')}")
                if data_verifications:
                    del node_data['data']['verifications']
            
            # 🛡️ PROTECTION: Normalize verification structure (ensure 'command' exists, not just 'method')
            if 'verifications' in node_data and isinstance(node_data['verifications'], list):
                normalized_verifications = []
                for v in node_data['verifications']:
                    if isinstance(v, dict):
                        # If 'method' exists but 'command' doesn't, migrate it
                        if 'method' in v and 'command' not in v:
                            v['command'] = v['method']
                            print(f"[@db:save_nodes_batch] 🔧 Auto-migrated verification: 'method' → 'command' = '{v['command']}'")
                        
                        # Ensure 'command' is not empty
                        if not v.get('command') or v.get('command', '').strip() == '':
                            print(f"[@db:save_nodes_batch] ⚠️ Skipping verification with missing/empty command")
                            continue
                        
                        normalized_verifications.append(v)
                
                node_data['verifications'] = normalized_verifications
            
            # Ensure style field is never null
            if 'style' not in node_data or node_data['style'] is None:
                node_data['style'] = {}
                
            processed_nodes.append(node_data)
            
        print(f"[@db:navigation_trees:save_nodes_batch] Saving {len(processed_nodes)} nodes in one batch...")
        
        # Perform Batch Upsert
        # on_conflict matches (tree_id, node_id) (composite PK or unique constraint)
        result = supabase.table('navigation_nodes').upsert(processed_nodes, on_conflict='tree_id, node_id').execute()
        
        print(f"[@db:navigation_trees:save_nodes_batch] ✅ Batch complete. Saved {len(result.data)} nodes.")
        
        return {'success': True, 'nodes': result.data}
        
    except Exception as e:
        print(f"[@db:navigation_trees:save_nodes_batch] Error: {e}")
        return {'success': False, 'error': str(e)}

def delete_node(tree_id: str, node_id: str, team_id: str) -> Dict:
    """Delete a node, all connected edges, and cascade delete any nested trees."""
    try:
        supabase = get_supabase()
        
        # First, find and delete any nested trees linked to this node
        subtrees_result = get_node_sub_trees(tree_id, node_id, team_id)
        if subtrees_result['success']:
            subtrees = subtrees_result['sub_trees']
            for subtree in subtrees:
                # Use cascade delete to remove the entire subtree hierarchy
                cascade_result = delete_tree_cascade(subtree['id'], team_id)
                if cascade_result['success']:
                    print(f"[@db:navigation_trees:delete_node] Cascade deleted subtree: {subtree['id']} for node: {node_id}")
                else:
                    print(f"[@db:navigation_trees:delete_node] Warning: Failed to delete subtree {subtree['id']}: {cascade_result['error']}")
        
        # Delete connected edges
        supabase.table('navigation_edges').delete()\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .or_(f'source_node_id.eq.{node_id},target_node_id.eq.{node_id}')\
            .execute()
        
        # Delete the node itself
        result = supabase.table('navigation_nodes').delete()\
            .eq('tree_id', tree_id)\
            .eq('node_id', node_id)\
            .eq('team_id', team_id)\
            .execute()
        
        print(f"[@db:navigation_trees:delete_node] Deleted node: {node_id}")
        
        # Invalidate cache after successful delete
        invalidate_navigation_cache_for_tree(tree_id, team_id)
        
        return {'success': True}
    except Exception as e:
        print(f"[@db:navigation_trees:delete_node] Error: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# EDGE OPERATIONS
# ============================================================================

def get_tree_edges(tree_id: str, team_id: str, node_ids: List[str] = None) -> Dict:
    """Get edges with action_sets structure ONLY - NO LEGACY SUPPORT."""
    try:
        supabase = get_supabase()
        
        # Use select('*') to stay aligned with get_tree_nodes: an explicit column list
        # makes this query fail (and silently return zero edges) whenever PostgREST's
        # schema cache is stale or a column was added/dropped, even though the wildcard
        # node query keeps working — which manifests as "nodes render but edges don't".
        # final_wait_time + threshold live per-direction inside action_sets; any extra
        # columns returned here are simply ignored downstream.
        query = supabase.table('navigation_edges')\
            .select('*')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)
        
        if node_ids:
            # Get edges that connect to any of the specified nodes
            node_filter = ','.join(node_ids)
            query = query.or_(f'source_node_id.in.({node_filter}),target_node_id.in.({node_filter})')
        
        result = query.order('created_at').execute()
        
        # STRICT: All edges must have action_sets field (can be empty array for initial setup)
        for edge in result.data:
            if 'action_sets' not in edge:
                raise ValueError(f"Edge {edge.get('edge_id')} missing action_sets - migration incomplete")
            if not edge.get('default_action_set_id'):
                raise ValueError(f"Edge {edge.get('edge_id')} missing default_action_set_id - migration incomplete")
        
        return {'success': True, 'edges': result.data}
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_edges] Error: {e}")
        return {'success': False, 'error': str(e)}

def get_edge_by_id(tree_id: str, edge_id: str, team_id: str) -> Dict:
    """Get a single edge by its edge_id."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_edges').select('*')\
            .eq('tree_id', tree_id)\
            .eq('edge_id', edge_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if result.data:
            print(f"[@db:navigation_trees:get_edge_by_id] Retrieved edge: {edge_id}")
            return {'success': True, 'edge': result.data[0]}
        else:
            print(f"[@db:navigation_trees:get_edge_by_id] Edge not found: {edge_id}")
            return {'success': False, 'error': 'Edge not found'}
    except Exception as e:
        print(f"[@db:navigation_trees:get_edge_by_id] Error: {e}")
        return {'success': False, 'error': str(e)}

def _validate_root_left_handle(supabase, tree_id: str, team_id: str, edges_data: List[Dict]) -> None:
    """The root node's left handle is reserved for the entry→root edge.

    Reject any edge that anchors on the root's left handle unless its source
    is the entry node ('left-target' into the root) — and never allow the
    root to emit from 'left-source'. All writers (REST, MCP, editor batch
    save) funnel through save_edge/save_edges_batch, so this is the single
    authoritative check. Nodes missing from the DB (e.g. same-batch creates
    ordered nodes-then-edges) resolve to {} and are not blocked.
    """
    suspects = [
        e for e in edges_data
        if (e.get('data') or {}).get('targetHandle') == 'left-target'
        or (e.get('data') or {}).get('sourceHandle') == 'left-source'
    ]
    if not suspects:
        return

    node_ids = {e['source_node_id'] for e in suspects} | {e['target_node_id'] for e in suspects}
    rows = supabase.table('navigation_nodes').select('node_id, data')\
        .eq('tree_id', tree_id)\
        .eq('team_id', team_id)\
        .in_('node_id', list(node_ids))\
        .execute()
    node_data = {row['node_id']: (row.get('data') or {}) for row in (rows.data or [])}

    for edge in suspects:
        handles = edge.get('data') or {}
        source = node_data.get(edge['source_node_id'], {})
        target = node_data.get(edge['target_node_id'], {})

        if (handles.get('targetHandle') == 'left-target'
                and target.get('is_root') is True
                and source.get('type') != 'entry'):
            raise ValueError(
                f"Edge {edge['source_node_id']}→{edge['target_node_id']}: 'left-target' on root node "
                f"'{edge['target_node_id']}' is reserved for the entry edge. "
                f"Use a menu handle ('top-right-menu-target') or 'right-target' instead."
            )

        if (handles.get('sourceHandle') == 'left-source'
                and source.get('is_root') is True
                and source.get('type') != 'entry'):
            raise ValueError(
                f"Edge {edge['source_node_id']}→{edge['target_node_id']}: 'left-source' on root node "
                f"'{edge['source_node_id']}' is reserved for the entry edge. "
                f"Use a menu handle ('bottom-right-menu-source') or 'right-source' instead."
            )


def save_edge(tree_id: str, edge_data: Dict, team_id: str) -> Dict:
    """Save edge with action_sets structure ONLY - NO LEGACY SUPPORT.

    Note: If 'label' is not provided or is empty, the database trigger
    will automatically generate it in format 'source_label→target_label'.
    """
    try:
        supabase = get_supabase()
        
        # STRICT: Only accept new action_sets format
        if 'action_sets' not in edge_data:
            raise ValueError("action_sets is required")
        
        if not edge_data.get('default_action_set_id'):
            raise ValueError("default_action_set_id is required")
        
        # Validate action_sets constraints
        action_sets = edge_data['action_sets']
        default_id = edge_data['default_action_set_id']
        
        # Validate maximum action sets limit (2 for bidirectional, 1 for unidirectional)
        if len(action_sets) > 2:
            raise ValueError(f"Maximum 2 action sets allowed per edge, got {len(action_sets)}")
        
        # Validate default_action_set_id exists in action_sets (skip if action_sets is empty for initial setup)
        if action_sets and not any(action_set.get('id') == default_id for action_set in action_sets):
            raise ValueError(f"default_action_set_id '{default_id}' not found in action_sets")

        # Root left handle is entry-only (see _validate_root_left_handle)
        _validate_root_left_handle(supabase, tree_id, team_id, [edge_data])

        edge_data['tree_id'] = tree_id
        edge_data['team_id'] = team_id
        edge_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        # Defensive strip: legacy callers may still pass final_wait_time even
        # though it now lives per-direction inside action_sets and the column
        # has been dropped. Keep this so a stale client can't error the write.
        edge_data.pop('final_wait_time', None)

        # Check if edge exists
        existing = supabase.table('navigation_edges').select('id')\
            .eq('tree_id', tree_id)\
            .eq('edge_id', edge_data['edge_id'])\
            .eq('team_id', team_id)\
            .execute()
        
        if existing.data:
            # Update existing edge
            result = supabase.table('navigation_edges').update(edge_data)\
                .eq('tree_id', tree_id)\
                .eq('edge_id', edge_data['edge_id'])\
                .eq('team_id', team_id)\
                .execute()
            print(f"[@db:navigation_trees:save_edge] Updated edge: {edge_data['edge_id']}")
        else:
            # Insert new edge
            edge_data['created_at'] = datetime.now(timezone.utc).isoformat()
            result = supabase.table('navigation_edges').insert(edge_data).execute()
            print(f"[@db:navigation_trees:save_edge] Created new edge: {edge_data['edge_id']}")
        
        # NOTE: Cache updates are handled by frontend calling /server/navigation/cache/update-edge
        # which proxies to all hosts for incremental NetworkX graph updates (graph.remove_edge + graph.add_edge)
        # This is O(1) incremental update - no full graph rebuild needed
        
        return {'success': True, 'edge': result.data[0]}
    except Exception as e:
        print(f"[@db:navigation_trees:save_edge] Error: {e}")
        return {'success': False, 'error': str(e)}

def save_edges_batch(tree_id: str, edges_data: List[Dict], team_id: str) -> Dict:
    """
    Save multiple edges in a single transaction (upsert).
    
    BENEFITS:
    1. Efficiency: 1 Network request vs N requests
    2. Trigger Control: Database trigger fires ONLY ONCE per batch.
    
    Enforces 'action_sets' structure.
    """
    try:
        supabase = get_supabase()
        
        processed_edges = []
        
        for edge_data in edges_data:
            # STRICT: Only accept new action_sets format
            if 'action_sets' not in edge_data:
                raise ValueError(f"Edge {edge_data.get('edge_id')} missing action_sets")
            
            if not edge_data.get('default_action_set_id'):
                raise ValueError(f"Edge {edge_data.get('edge_id')} missing default_action_set_id")
            
            # Prepare fields
            edge_data['tree_id'] = tree_id
            edge_data['team_id'] = team_id
            edge_data['updated_at'] = datetime.now(timezone.utc).isoformat()
            # Defensive strip: see save_edge() above for rationale.
            edge_data.pop('final_wait_time', None)

            if 'created_at' not in edge_data:
                edge_data['created_at'] = datetime.now(timezone.utc).isoformat()

            processed_edges.append(edge_data)

        # Root left handle is entry-only (see _validate_root_left_handle)
        _validate_root_left_handle(supabase, tree_id, team_id, processed_edges)

        print(f"[@db:navigation_trees:save_edges_batch] Saving {len(processed_edges)} edges in one batch...")
        
        # Perform Batch Upsert
        # on_conflict matches (tree_id, edge_id) (composite PK or unique constraint)
        result = supabase.table('navigation_edges').upsert(processed_edges, on_conflict='tree_id, edge_id').execute()
        
        print(f"[@db:navigation_trees:save_edges_batch] ✅ Batch complete. Saved {len(result.data)} edges.")
        
        return {'success': True, 'edges': result.data}
        
    except Exception as e:
        print(f"[@db:navigation_trees:save_edges_batch] Error: {e}")
        return {'success': False, 'error': str(e)}

def delete_edge(tree_id: str, edge_id: str, team_id: str) -> Dict:
    """Delete an edge."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_edges').delete()\
            .eq('tree_id', tree_id)\
            .eq('edge_id', edge_id)\
            .eq('team_id', team_id)\
            .execute()
        
        print(f"[@db:navigation_trees:delete_edge] Deleted edge: {edge_id}")
        
        # Invalidate cache after successful delete
        invalidate_navigation_cache_for_tree(tree_id, team_id)
        
        return {'success': True}
    except Exception as e:
        print(f"[@db:navigation_trees:delete_edge] Error: {e}")
        return {'success': False, 'error': str(e)}

def batch_delete_edges_except(tree_id: str, team_id: str, keep_edge_ids: List[str]) -> Dict:
    """
    Delete all edges in a tree EXCEPT specified ones (batch operation).
    
    Args:
        tree_id: Tree ID
        team_id: Team ID
        keep_edge_ids: List of edge IDs to keep (e.g., ['edge-entry-node-to-home'])
    
    Returns:
        {'success': True, 'deleted_count': int}
    """
    try:
        supabase = get_supabase()
        
        # Fetch all edge IDs for this tree
        all_edges = supabase.table('navigation_edges')\
            .select('edge_id')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if not all_edges.data:
            print(f"[@db:navigation_trees:batch_delete_edges_except] No edges found for tree {tree_id}")
            return {'success': True, 'deleted_count': 0}
        
        # Filter out the ones to keep
        all_edge_ids = [e['edge_id'] for e in all_edges.data]
        edges_to_delete = [eid for eid in all_edge_ids if eid not in keep_edge_ids]
        
        print(f"[@db:navigation_trees:batch_delete_edges_except] Found {len(all_edge_ids)} total edges")
        print(f"[@db:navigation_trees:batch_delete_edges_except] Keep list: {keep_edge_ids}")
        print(f"[@db:navigation_trees:batch_delete_edges_except] To delete: {len(edges_to_delete)} edges")
        
        if not edges_to_delete:
            print(f"[@db:navigation_trees:batch_delete_edges_except] No edges to delete (all are in keep list)")
            return {'success': True, 'deleted_count': 0}
        
        # Delete in batch using IN clause
        print(f"[@db:navigation_trees:batch_delete_edges_except] Executing DELETE with IN clause for {len(edges_to_delete)} edges...")
        result = supabase.table('navigation_edges').delete()\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .in_('edge_id', edges_to_delete)\
            .execute()
        
        deleted_count = len(result.data) if result.data else 0
        print(f"[@db:navigation_trees:batch_delete_edges_except] DELETE result: {result.data if result.data else 'None'}")
        print(f"[@db:navigation_trees:batch_delete_edges_except] Deleted {deleted_count} edges (kept {len(keep_edge_ids)} edges)")
        
        # Invalidate cache after successful delete (only once!)
        invalidate_navigation_cache_for_tree(tree_id, team_id)
        
        return {'success': True, 'deleted_count': deleted_count}
    except Exception as e:
        print(f"[@db:navigation_trees:batch_delete_edges_except] Error: {e}")
        return {'success': False, 'error': str(e)}

def batch_delete_nodes_except(tree_id: str, team_id: str, keep_node_ids: List[str]) -> Dict:
    """
    Delete all nodes in a tree EXCEPT specified ones (batch operation).
    
    Args:
        tree_id: Tree ID
        team_id: Team ID
        keep_node_ids: List of node IDs to keep (e.g., ['entry-node', 'home'])
    
    Returns:
        {'success': True, 'deleted_count': int}
    """
    try:
        supabase = get_supabase()
        
        # Fetch all node IDs for this tree
        all_nodes = supabase.table('navigation_nodes')\
            .select('node_id')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if not all_nodes.data:
            print(f"[@db:navigation_trees:batch_delete_nodes_except] No nodes found for tree {tree_id}")
            return {'success': True, 'deleted_count': 0}
        
        # Filter out the ones to keep
        all_node_ids = [n['node_id'] for n in all_nodes.data]
        nodes_to_delete = [nid for nid in all_node_ids if nid not in keep_node_ids]
        
        print(f"[@db:navigation_trees:batch_delete_nodes_except] Found {len(all_node_ids)} total nodes")
        print(f"[@db:navigation_trees:batch_delete_nodes_except] Keep list: {keep_node_ids}")
        print(f"[@db:navigation_trees:batch_delete_nodes_except] To delete: {len(nodes_to_delete)} nodes: {nodes_to_delete[:5]}...")
        
        if not nodes_to_delete:
            print(f"[@db:navigation_trees:batch_delete_nodes_except] No nodes to delete (all are in keep list)")
            return {'success': True, 'deleted_count': 0}
        
        # Delete in batch using IN clause
        print(f"[@db:navigation_trees:batch_delete_nodes_except] Executing DELETE with IN clause for {len(nodes_to_delete)} nodes...")
        result = supabase.table('navigation_nodes').delete()\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .in_('node_id', nodes_to_delete)\
            .execute()
        
        deleted_count = len(result.data) if result.data else 0
        print(f"[@db:navigation_trees:batch_delete_nodes_except] DELETE result: {result.data if result.data else 'None'}")
        print(f"[@db:navigation_trees:batch_delete_nodes_except] Deleted {deleted_count} nodes (kept {len(keep_node_ids)} nodes)")
        
        # Invalidate cache after successful delete (only once!)
        invalidate_navigation_cache_for_tree(tree_id, team_id)
        
        return {'success': True, 'deleted_count': deleted_count}
    except Exception as e:
        print(f"[@db:navigation_trees:batch_delete_nodes_except] Error: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# NESTED TREE OPERATIONS
# ============================================================================

def get_node_sub_trees(tree_id: str, node_id: str, team_id: str) -> Dict:
    """Get all sub-trees that belong to a specific node."""
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees').select('*')\
            .eq('parent_tree_id', tree_id)\
            .eq('parent_node_id', node_id)\
            .eq('team_id', team_id)\
            .order('created_at')\
            .execute()
        
        print(f"[@db:navigation_trees:get_node_sub_trees] Retrieved {len(result.data)} sub-trees for node: {node_id}")
        return {
            'success': True,
            'sub_trees': result.data
        }
    except Exception as e:
        print(f"[@db:navigation_trees:get_node_sub_trees] Error: {e}")
        return {'success': False, 'error': str(e)}

def create_sub_tree(parent_tree_id: str, parent_node_id: str, tree_data: Dict, team_id: str) -> Dict:
    """Create a new sub-tree linked to a parent node."""
    try:
        supabase = get_supabase()
        
        # Get parent tree depth and userinterface_id
        parent_result = supabase.table('navigation_trees').select('tree_depth, userinterface_id')\
            .eq('id', parent_tree_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if not parent_result.data:
            return {'success': False, 'error': 'Parent tree not found'}
        
        parent_depth = parent_result.data[0]['tree_depth']
        parent_userinterface_id = parent_result.data[0].get('userinterface_id')
        
        # Validate depth limit
        if parent_depth >= 5:
            return {'success': False, 'error': 'Maximum nesting depth reached (5 levels)'}
        
        # Inherit userinterface_id from parent if not provided
        if 'userinterface_id' not in tree_data or tree_data['userinterface_id'] is None:
            tree_data['userinterface_id'] = parent_userinterface_id
        
        # Set nested tree properties
        tree_data.update({
            'parent_tree_id': parent_tree_id,
            'parent_node_id': parent_node_id,
            'tree_depth': parent_depth + 1,
            'is_root_tree': False,
            'team_id': team_id,
            'id': str(uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        })
        
        # Create the sub-tree
        result = supabase.table('navigation_trees').insert(tree_data).execute()
        
        print(f"[@db:navigation_trees:create_sub_tree] Created sub-tree: {tree_data['id']} for node: {parent_node_id}")
        return {'success': True, 'tree': result.data[0]}
        
    except Exception as e:
        print(f"[@db:navigation_trees:create_sub_tree] Error: {e}")
        return {'success': False, 'error': str(e)}

def get_tree_hierarchy(root_tree_id: str, team_id: str) -> Dict:
    """Get complete tree hierarchy starting from root."""
    try:
        supabase = get_supabase()
        
        # Use the SQL function to get all descendant trees
        result = supabase.rpc('get_descendant_trees', {'root_tree_id': root_tree_id}).execute()
        
        return {
            'success': True,
            'hierarchy': result.data
        }
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_hierarchy] Error: {e}")
        return {'success': False, 'error': str(e)}

def get_tree_breadcrumb(tree_id: str, team_id: str) -> Dict:
    """Get breadcrumb path for a tree."""
    try:
        supabase = get_supabase()
        
        # Use the SQL function to get tree path
        result = supabase.rpc('get_tree_path', {'target_tree_id': tree_id}).execute()
        
        print(f"[@db:navigation_trees:get_tree_breadcrumb] Retrieved breadcrumb for tree: {tree_id}")
        return {
            'success': True,
            'breadcrumb': result.data
        }
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_breadcrumb] Error: {e}")
        return {'success': False, 'error': str(e)}


def get_complete_tree_hierarchy(root_tree_id: str, team_id: str) -> Dict[str, Any]:
    """
    Get complete tree hierarchy for unified pathfinding
    FAIL EARLY: Returns error if hierarchy cannot be built
    
    Args:
        root_tree_id: Root navigation tree ID
        team_id: Team ID for security
        
    Returns:
        Dictionary with complete hierarchy data ready for unified pathfinding
    """
    try:
        from shared.src.lib.utils.navigation_exceptions import DatabaseError

        # Resolve every tree id FIRST, then read the whole hierarchy in one
        # query. Reading the MV per tree cost one round trip each — ~200ms
        # apiece from a remote host, i.e. 3.2s for a 26-tree hierarchy, on
        # every save (this runs from _save_tree_to_history).
        descendant_trees = get_descendant_trees_data(root_tree_id, team_id)
        full_by_id = _get_full_trees_batch(
            [root_tree_id] + [d['tree_id'] for d in descendant_trees], team_id)

        root_tree = full_by_id.get(root_tree_id)
        if not root_tree:
            raise DatabaseError(f"Failed to load root tree: {root_tree_id} not found in materialized view")
        if not root_tree.get('tree'):
            raise DatabaseError(f"Root tree {root_tree_id} has no tree metadata")

        root_nodes = root_tree.get('nodes') or []
        root_edges = root_tree.get('edges') or []

        # Build complete hierarchy data
        hierarchy_data = []
        total_nodes = len(root_nodes)
        total_edges = len(root_edges)

        # Add root tree
        hierarchy_data.append({
            'tree_id': root_tree_id,
            'tree': root_tree['tree'],  # full row so restores keep viewport etc.
            'tree_info': {
                'name': root_tree['tree'].get('name', root_tree_id),
                'userinterface_id': root_tree['tree'].get('userinterface_id'),
                'is_root_tree': True,
                'tree_depth': 0,
                'parent_tree_id': None,
                'parent_node_id': None
            },
            'nodes': root_nodes,
            'edges': root_edges
        })

        # Add nested trees
        for nested_tree_info in descendant_trees:
            nested_tree_id = nested_tree_info['tree_id']

            nested_data = full_by_id.get(nested_tree_id)
            if nested_data:
                # Validate nested tree structure
                if not nested_data.get('tree'):
                    print(f"[@db:navigation_trees:get_complete_tree_hierarchy] ⚠️ Skipping tree {nested_tree_id} - no tree metadata")
                    continue

                nested_nodes = nested_data.get('nodes') or []
                nested_edges = nested_data.get('edges') or []

                hierarchy_data.append({
                    'tree_id': nested_tree_id,
                    'tree': nested_data['tree'],  # full row so restores keep viewport etc.
                    'tree_info': {
                        'name': nested_tree_info.get('tree_name', nested_tree_id),
                        'userinterface_id': nested_data['tree'].get('userinterface_id'),
                        'is_root_tree': False,
                        'tree_depth': nested_tree_info.get('depth', 0),
                        'parent_tree_id': nested_tree_info.get('parent_tree_id'),
                        'parent_node_id': nested_tree_info.get('parent_node_id')
                    },
                    'nodes': nested_nodes,
                    'edges': nested_edges
                })
                total_nodes += len(nested_nodes)
                total_edges += len(nested_edges)

        max_depth = max([t['tree_info']['tree_depth'] for t in hierarchy_data]) if hierarchy_data else 0
        
        # Single summary log with essential information
        print(f"[@db:navigation_trees:get_complete_tree_hierarchy] Complete hierarchy: {len(hierarchy_data)} trees, {total_nodes} nodes, {total_edges} edges, max depth: {max_depth}")
        
        return {
            'success': True,
            'all_trees_data': hierarchy_data,  # This is the format expected by populate_unified_cache
            'hierarchy': hierarchy_data,       # Keep for backward compatibility
            'total_trees': len(hierarchy_data),
            'max_depth': max_depth,
            'has_nested_trees': len(hierarchy_data) > 1
        }
        
    except Exception as e:
        print(f"[@db:navigation_trees:get_complete_tree_hierarchy] Error: {e}")
        return {
            'success': False,
            'error': f"Failed to build tree hierarchy: {str(e)}"
        }


def get_descendant_trees_data(root_tree_id: str, team_id: str) -> List[Dict]:
    """
    Get all descendant trees with full metadata for hierarchy building
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID for security
        
    Returns:
        List of descendant tree metadata dictionaries
    """
    try:
        # Use existing get_tree_hierarchy function
        hierarchy_result = get_tree_hierarchy(root_tree_id, team_id)
        
        if not hierarchy_result['success']:
            return []
        
        hierarchy_trees = hierarchy_result['hierarchy']
        
        # Filter out the root tree (depth 0) to get only descendants
        descendant_trees = [tree for tree in hierarchy_trees if tree.get('depth', 0) > 0]
        
        return descendant_trees
        
    except Exception as e:
        print(f"[@db:navigation_trees:get_descendant_trees_data] Error: {e}")
        return []

def delete_tree_cascade(tree_id: str, team_id: str) -> Dict:
    """Delete a tree and all its descendant trees."""
    try:
        supabase = get_supabase()
        
        # Get all descendant trees first
        hierarchy_result = get_tree_hierarchy(tree_id, team_id)
        if not hierarchy_result['success']:
            return hierarchy_result
        
        # Delete all trees in reverse depth order (deepest first)
        trees_to_delete = sorted(hierarchy_result['hierarchy'], key=lambda x: x['depth'], reverse=True)
        
        for tree in trees_to_delete:
            # Delete tree (cascade will handle nodes and edges)
            supabase.table('navigation_trees').delete().eq('id', tree['tree_id']).eq('team_id', team_id).execute()
            print(f"[@db:navigation_trees:delete_tree_cascade] Deleted tree: {tree['tree_id']}")
        
        return {'success': True, 'deleted_count': len(trees_to_delete)}
        
    except Exception as e:
        print(f"[@db:navigation_trees:delete_tree_cascade] Error: {e}")
        return {'success': False, 'error': str(e)}

def move_subtree(subtree_id: str, new_parent_tree_id: str, new_parent_node_id: str, team_id: str) -> Dict:
    """Move a subtree to a different parent node."""
    try:
        supabase = get_supabase()
        
        # Get new parent depth
        parent_result = supabase.table('navigation_trees').select('tree_depth')\
            .eq('id', new_parent_tree_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if not parent_result.data:
            return {'success': False, 'error': 'New parent tree not found'}
        
        new_parent_depth = parent_result.data[0]['tree_depth']
        
        # Get current subtree depth to check if move is valid
        subtree_result = supabase.table('navigation_trees').select('tree_depth')\
            .eq('id', subtree_id)\
            .eq('team_id', team_id)\
            .execute()
        
        if not subtree_result.data:
            return {'success': False, 'error': 'Subtree not found'}
        
        # Calculate new depth and validate
        depth_difference = subtree_result.data[0]['tree_depth'] - new_parent_depth - 1
        if new_parent_depth + 1 + depth_difference > 5:
            return {'success': False, 'error': 'Move would exceed maximum nesting depth'}
        
        # Update subtree parent relationships
        result = supabase.table('navigation_trees').update({
            'parent_tree_id': new_parent_tree_id,
            'parent_node_id': new_parent_node_id,
            'tree_depth': new_parent_depth + 1,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', subtree_id).eq('team_id', team_id).execute()
        
        print(f"[@db:navigation_trees:move_subtree] Moved subtree: {subtree_id} to node: {new_parent_node_id}")
        return {'success': True, 'tree': result.data[0]}
        
    except Exception as e:
        print(f"[@db:navigation_trees:move_subtree] Error: {e}")
        return {'success': False, 'error': str(e)}

# ============================================================================
# TREE HISTORY & VERSIONING
# ============================================================================

def _save_tree_to_history(tree_id: str, team_id: str, modification_type: str = 'update', modified_by: str = None) -> bool:
    """
    Save complete tree hierarchy snapshot to history for restoration.

    Captures:
    - Root tree metadata
    - All subtrees in hierarchy
    - All nodes from all trees
    - All edges from all trees
    - Complete structure for full restoration
    """
    try:
        supabase = get_supabase()

        # Get complete tree hierarchy (root + all subtrees)
        hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
        if not hierarchy_result['success']:
            print(f"[@db:navigation_trees:_save_tree_to_history] Failed to get hierarchy: {hierarchy_result.get('error')}")
            return False

        # Get current version number for this tree
        version_query = supabase.table('navigation_trees_history')\
            .select('version_number')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(1)\
            .execute()

        next_version = 1
        if version_query.data:
            next_version = version_query.data[0]['version_number'] + 1

        # Prepare complete tree data snapshot
        tree_snapshot = {
            'hierarchy': hierarchy_result['all_trees_data'],  # Complete hierarchy with all subtrees
            'root_tree_id': tree_id,
            'total_trees': len(hierarchy_result['all_trees_data']),
            'total_nodes': sum(len(tree_data.get('nodes', [])) for tree_data in hierarchy_result['all_trees_data']),
            'total_edges': sum(len(tree_data.get('edges', [])) for tree_data in hierarchy_result['all_trees_data']),
            'snapshot_timestamp': datetime.now(timezone.utc).isoformat()
        }

        # Save to history
        history_record = {
            'tree_id': tree_id,
            'team_id': team_id,
            'version_number': next_version,
            'modification_type': modification_type,
            'modified_by': modified_by,
            'tree_data': tree_snapshot,
            'changes_summary': f"Complete tree hierarchy snapshot (v{next_version}): {tree_snapshot['total_trees']} trees, {tree_snapshot['total_nodes']} nodes, {tree_snapshot['total_edges']} edges"
        }

        supabase.table('navigation_trees_history').insert(history_record).execute()
        print(f"[@db:navigation_trees:_save_tree_to_history] Saved v{next_version} snapshot for tree {tree_id}: {tree_snapshot['total_trees']} trees, {tree_snapshot['total_nodes']} nodes, {tree_snapshot['total_edges']} edges")
        return True

    except Exception as e:
        print(f"[@db:navigation_trees:_save_tree_to_history] Error: {e}")
        return False

def get_tree_history(tree_id: str, team_id: str, limit: int = 10) -> Dict:
    """Get the most recent versions of a tree from history (default 10).

    Caps the row count at the DB layer so we don't deserialise hundreds of full
    tree snapshots just to render a short version list.
    """
    try:
        supabase = get_supabase()
        result = supabase.table('navigation_trees_history')\
            .select('*')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(limit)\
            .execute()

        return {
            'success': True,
            'versions': result.data
        }
    except Exception as e:
        print(f"[@db:navigation_trees:get_tree_history] Error: {e}")
        return {'success': False, 'error': str(e)}

_restore_lock = threading.Lock()
_restores_in_progress = set()

def _live_columns(supabase, table: str) -> Optional[set]:
    """Column names the deployed table actually has, or None if unknowable."""
    probe = supabase.table(table).select('*').limit(1).execute()
    return set(probe.data[0].keys()) if probe.data else None

def _restore_row(src: Dict, live_cols: Optional[set], tree_id: str, team_id: str, now: str) -> Dict:
    """Copy a snapshot node/edge verbatim, minus columns the live table lacks.

    The surrogate `id` is dropped on purpose: rows are matched by their semantic
    key (tree_id, node_id/edge_id) — the one everything else references — and
    re-keying a primary key mid-upsert risks colliding with a live row.
    """
    row = {k: v for k, v in src.items()
           if k != 'id' and (live_cols is None or k in live_cols)}
    row['tree_id'] = tree_id
    row['team_id'] = team_id
    row['updated_at'] = now
    return row

def restore_tree_from_history(tree_id: str, version_number: int, team_id: str, restored_by: str = None) -> Dict:
    """
    Restore a tree IN PLACE from a history snapshot, preserving the snapshot's
    original tree/node/edge ids — a restore yields the exact tree as it was, so
    history keying, caches and external references (execution results, reports,
    bookmarks) stay valid.

    Versioning is Grafana-style: the current state is snapshotted first (so the
    restore is undoable), then a new version is recorded as a duplicate of the
    restored one. Example: on version 53, restoring version 34 writes v54 (state
    before restore) and v55 (copy of v34, now live).

    Rejects concurrent restores of the same tree: a restore replaces the whole
    hierarchy, so two running at once duplicate it.
    """
    with _restore_lock:
        if tree_id in _restores_in_progress:
            return {'success': False, 'error': 'A restore is already in progress for this tree'}
        _restores_in_progress.add(tree_id)
    try:
        return _restore_tree_from_history_impl(tree_id, version_number, team_id, restored_by)
    finally:
        with _restore_lock:
            _restores_in_progress.discard(tree_id)

def _restore_tree_from_history_impl(tree_id: str, version_number: int, team_id: str, restored_by: str = None) -> Dict:
    try:
        # modified_by is a uuid column; callers historically sent labels like
        # 'user', which aborted the restore-record insert at the very last step.
        if restored_by:
            try:
                UUID(str(restored_by))
            except ValueError:
                restored_by = None
        supabase = get_supabase()

        # Get the history version to restore from
        history_result = supabase.table('navigation_trees_history')\
            .select('*')\
            .eq('tree_id', tree_id)\
            .eq('version_number', version_number)\
            .eq('team_id', team_id)\
            .execute()

        if not history_result.data:
            return {'success': False, 'error': f'History version {version_number} not found for tree {tree_id}'}

        history_record = history_result.data[0]
        tree_snapshot = history_record['tree_data']

        # Snapshots saved before tree_info carried userinterface_id lack the key,
        # so resolve it from the live tree row and use it as the fallback.
        live_tree = supabase.table('navigation_trees')\
            .select('userinterface_id')\
            .eq('id', tree_id)\
            .eq('team_id', team_id)\
            .execute()
        fallback_userinterface_id = live_tree.data[0]['userinterface_id'] if live_tree.data else None

        snapshot_userinterface_id = next(
            (t['tree_info'].get('userinterface_id') for t in tree_snapshot['hierarchy']
             if t['tree_info'].get('userinterface_id')),
            None
        )
        userinterface_id = snapshot_userinterface_id or fallback_userinterface_id
        if not userinterface_id:
            return {'success': False, 'error': f'Cannot resolve userinterface_id for tree {tree_id}'}

        trees_data = sorted(tree_snapshot['hierarchy'], key=lambda x: x['tree_info']['tree_depth'])
        if not trees_data:
            return {'success': False, 'error': f'Snapshot v{version_number} has no hierarchy data'}
        restored_root_id = tree_snapshot.get('root_tree_id') or next(
            (t['tree_id'] for t in trees_data if t['tree_info'].get('is_root_tree')), tree_id)

        # Snapshot the CURRENT state first — history snapshots are taken before
        # saves, so the live state isn't in history yet. This keeps the restore
        # undoable. Abort if it fails: never wipe a state that has no snapshot.
        if not _save_tree_to_history(tree_id, team_id, 'update', restored_by):
            return {'success': False, 'error': 'Failed to snapshot current state before restore'}

        current_version_result = supabase.table('navigation_trees_history')\
            .select('version_number')\
            .eq('tree_id', tree_id)\
            .eq('team_id', team_id)\
            .order('version_number', desc=True)\
            .limit(1)\
            .execute()
        next_version = (current_version_result.data[0]['version_number'] + 1) if current_version_result.data else 1

        print(f"[@db:navigation_trees:restore_tree_from_history] Restoring v{version_number} in place (pre-restore state saved as v{next_version - 1})")

        # Build all rows up front, preserving the snapshot's original ids. Every
        # statement on the navigation tables fires a full mv_full_navigation_trees
        # refresh, so everything below is batched — row-by-row loops die with
        # statement timeouts (57014) on large hierarchies.
        # Rows are copied verbatim from the snapshot, keeping only keys the live
        # table still has. This is what makes a restore an exact copy: it carries
        # every column the snapshot holds (hidden_in_base, style, …) without
        # hand-listing, and silently drops columns since removed from the schema
        # (e.g. variant_overrides, dropped 2026-05-05 for the named-variant model).
        #
        # Columns the snapshot does NOT carry are deliberately not sent, so the
        # live value survives the upsert. That is exactly right for the
        # protection flags (is_system_protected / is_read_only), which the MV
        # doesn't expose: protected rows are never wiped, so their flags must be
        # preserved, while re-inserted rows were unprotected by definition and
        # correctly take the column DEFAULT.
        node_cols = _live_columns(supabase, 'navigation_nodes')
        edge_cols = _live_columns(supabase, 'navigation_edges')

        now = datetime.now(timezone.utc).isoformat()
        tree_rows_by_depth = {}
        node_rows = []
        edge_rows = []

        for entry in trees_data:
            info = entry['tree_info']
            snapshot_tree_row = entry.get('tree') or {}  # full row, present in newer snapshots
            depth = info.get('tree_depth', 0)

            tree_rows_by_depth.setdefault(depth, []).append({
                'id': entry['tree_id'],
                'name': info['name'],
                'userinterface_id': info.get('userinterface_id') or userinterface_id,
                'is_root_tree': info.get('is_root_tree', False),
                'tree_depth': depth,
                'parent_tree_id': info.get('parent_tree_id'),
                'parent_node_id': info.get('parent_node_id'),  # plain text, no FK — safe before nodes exist
                'viewport_x': snapshot_tree_row.get('viewport_x', 0),
                'viewport_y': snapshot_tree_row.get('viewport_y', 0),
                'viewport_zoom': snapshot_tree_row.get('viewport_zoom', 1),
                'team_id': team_id,
                'updated_at': now
            })

            for node in entry.get('nodes') or []:
                node_rows.append(_restore_row(node, node_cols, entry['tree_id'], team_id, now))

            for edge in entry.get('edges') or []:
                edge_rows.append(_restore_row(edge, edge_cols, entry['tree_id'], team_id, now))

        # Current live hierarchy of the interface
        live_trees = supabase.table('navigation_trees')\
            .select('id,tree_depth')\
            .eq('userinterface_id', userinterface_id)\
            .eq('team_id', team_id)\
            .execute()
        live_ids = [t['id'] for t in live_trees.data]
        snapshot_ids = {t['tree_id'] for t in trees_data}

        # 1) Wipe live nodes/edges (chunked), EXCEPT rows a bulk delete must not
        #    touch — they get upserted in step 3 instead:
        #    - system-protected rows (and nodes named entry-node/home): direct
        #      deletes are refused by trigger while their tree exists
        #    - has_subtree nodes: cascade_delete_subtrees_trigger would delete
        #      their subtree TREES (and those trees' history) on node delete
        # 5 trees per statement — 20 blew the DB statement timeout on example_tv
        WIPE_CHUNK = 5
        for i in range(0, len(live_ids), WIPE_CHUNK):
            chunk = live_ids[i:i + WIPE_CHUNK]
            supabase.table('navigation_edges').delete().eq('team_id', team_id)\
                .in_('tree_id', chunk).eq('is_system_protected', False).execute()
            supabase.table('navigation_nodes').delete().eq('team_id', team_id)\
                .in_('tree_id', chunk).eq('is_system_protected', False)\
                .eq('has_subtree', False)\
                .not_.in_('node_id', ['entry-node', 'home']).execute()

        # 2) Upsert snapshot trees level by level (parent_tree_id FK), ids kept
        for depth in sorted(tree_rows_by_depth):
            supabase.table('navigation_trees').upsert(tree_rows_by_depth[depth]).execute()

        # 3) Bulk upsert nodes and edges with their original identifiers —
        #    on_conflict updates the protected rows that survived the wipe
        CHUNK = 200
        for i in range(0, len(node_rows), CHUNK):
            supabase.table('navigation_nodes').upsert(
                node_rows[i:i + CHUNK], on_conflict='tree_id,node_id').execute()
        for i in range(0, len(edge_rows), CHUNK):
            supabase.table('navigation_edges').upsert(
                edge_rows[i:i + CHUNK], on_conflict='tree_id,edge_id').execute()

        # 3b) Rows that survived the wipe (protected / has_subtree) but aren't in
        #     the snapshot are removed one batch at a time. Skip protected ones —
        #     they can't be deleted while the tree lives; better a stale system
        #     row than a failed restore.
        snap_node_keys = {(r['tree_id'], r['node_id']) for r in node_rows}
        snap_edge_keys = {(r['tree_id'], r['edge_id']) for r in edge_rows}
        snapshot_id_list = sorted(snapshot_ids)
        leftover_node_ids = []
        leftover_edge_ids = []
        for i in range(0, len(snapshot_id_list), 20):
            chunk = snapshot_id_list[i:i + 20]
            live_nodes = supabase.table('navigation_nodes').select('id,tree_id,node_id,is_system_protected')\
                .eq('team_id', team_id).in_('tree_id', chunk).execute()
            leftover_node_ids += [
                n['id'] for n in live_nodes.data
                if (n['tree_id'], n['node_id']) not in snap_node_keys
                and not n.get('is_system_protected') and n['node_id'] not in ('entry-node', 'home')]
            live_edges = supabase.table('navigation_edges').select('id,tree_id,edge_id,is_system_protected')\
                .eq('team_id', team_id).in_('tree_id', chunk).execute()
            leftover_edge_ids += [
                e['id'] for e in live_edges.data
                if (e['tree_id'], e['edge_id']) not in snap_edge_keys and not e.get('is_system_protected')]
        for i in range(0, len(leftover_edge_ids), 25):
            supabase.table('navigation_edges').delete().eq('team_id', team_id)\
                .in_('id', leftover_edge_ids[i:i + 25]).execute()
        # deleting a has_subtree node cascades its subtrees — correct here, since
        # a subtree of a node absent from the snapshot is itself extra
        for i in range(0, len(leftover_node_ids), 25):
            supabase.table('navigation_nodes').delete().eq('team_id', team_id)\
                .in_('id', leftover_node_ids[i:i + 25]).execute()
        if leftover_node_ids or leftover_edge_ids:
            print(f"[@db:navigation_trees:restore_tree_from_history] Removed {len(leftover_node_ids)} leftover nodes, {len(leftover_edge_ids)} leftover edges")

        print(f"[@db:navigation_trees:restore_tree_from_history] Restored {len(snapshot_ids)} trees, {len(node_rows)} nodes, {len(edge_rows)} edges in place")

        # 4) If the live root differs from the snapshot's (a legacy fresh-id
        #    restore changed it), move the history chain BEFORE deleting the live
        #    root: history rows cascade-delete with their tree.
        if restored_root_id != tree_id:
            supabase.table('navigation_trees_history').update({'tree_id': restored_root_id})\
                .eq('tree_id', tree_id)\
                .eq('team_id', team_id)\
                .execute()

        # 5) Drop live trees that aren't part of the snapshot (deepest first, in
        #    small chunks — a whole-hierarchy cascade exceeds the DB timeout)
        extra = [t for t in live_trees.data if t['id'] not in snapshot_ids]
        extra_ids = [t['id'] for t in sorted(extra, key=lambda t: -(t['tree_depth'] or 0))]
        DELETE_CHUNK = 5
        for i in range(0, len(extra_ids), DELETE_CHUNK):
            supabase.table('navigation_trees').delete()\
                .eq('team_id', team_id)\
                .in_('id', extra_ids[i:i + DELETE_CHUNK])\
                .execute()
        if extra_ids:
            print(f"[@db:navigation_trees:restore_tree_from_history] Removed {len(extra_ids)} trees not present in v{version_number}")

        # 6) Restore record — content is an exact copy of the restored snapshot
        restoration_record = {
            'tree_id': restored_root_id,
            'team_id': team_id,
            'version_number': next_version,
            'modification_type': 'restore',
            'modified_by': restored_by,
            'tree_data': {**tree_snapshot, 'restored_from_version': version_number, 'snapshot_timestamp': now},
            'changes_summary': f"Restored version {version_number} in place as version {next_version}",
            'restored_from_version': version_number
        }
        supabase.table('navigation_trees_history').insert(restoration_record).execute()

        # Invalidate caches (both roots when a legacy restore had changed the id)
        invalidate_navigation_cache_for_tree(tree_id, team_id)
        if restored_root_id != tree_id:
            invalidate_navigation_cache_for_tree(restored_root_id, team_id)

        print(f"[@db:navigation_trees:restore_tree_from_history] v{version_number} restored in place as v{next_version}")

        return {
            'success': True,
            'new_version': next_version,
            'restored_from_version': version_number,
            'new_root_tree_id': restored_root_id,
            'trees_created': len(snapshot_ids),
            'nodes_created': len(node_rows),
            'edges_created': len(edge_rows)
        }

    except Exception as e:
        print(f"[@db:navigation_trees:restore_tree_from_history] Error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

# ============================================================================
# BATCH OPERATIONS
# ============================================================================

def save_tree_data(tree_id: str, nodes: List[Dict], edges: List[Dict], team_id: str, deleted_node_ids: List[str] = None, deleted_edge_ids: List[str] = None, viewport: Dict = None) -> Dict:
    """Save complete tree data (nodes + edges) in batch with deletions."""
    try:
        supabase = get_supabase()

        # 🆕 BEFORE saving changes, create a complete tree hierarchy snapshot
        _save_tree_to_history(tree_id, team_id, 'update')
        
        # ✅ Batch delete edges in ONE query
        if deleted_edge_ids and len(deleted_edge_ids) > 0:
            supabase.table('navigation_edges')\
                .delete()\
                .eq('tree_id', tree_id)\
                .eq('team_id', team_id)\
                .in_('edge_id', deleted_edge_ids)\
                .execute()
            print(f"[@db:navigation_trees:save_tree_data] Batch deleted {len(deleted_edge_ids)} edges")
        
        # ✅ Batch delete nodes in ONE query
        if deleted_node_ids and len(deleted_node_ids) > 0:
            supabase.table('navigation_nodes')\
                .delete()\
                .eq('tree_id', tree_id)\
                .eq('team_id', team_id)\
                .in_('node_id', deleted_node_ids)\
                .execute()
            print(f"[@db:navigation_trees:save_tree_data] Batch deleted {len(deleted_node_ids)} nodes")
        
        # Update tree viewport if provided
        if viewport:
            supabase.table('navigation_trees').update({
                'viewport_x': viewport.get('x', 0),
                'viewport_y': viewport.get('y', 0), 
                'viewport_zoom': viewport.get('zoom', 1)
            }).eq('id', tree_id).eq('team_id', team_id).execute()

        # Save/update current nodes and edges
        saved_nodes = []
        saved_edges = []
        
        # Save all nodes
        for node_data in nodes:
            result = save_node(tree_id, node_data, team_id)
            if result['success']:
                saved_nodes.append(result['node'])
            else:
                return {'success': False, 'error': f"Failed to save node {node_data.get('node_id')}: {result['error']}"}
        
        # Save all edges
        for edge_data in edges:
            result = save_edge(tree_id, edge_data, team_id)
            if result['success']:
                saved_edges.append(result['edge'])
            else:
                return {'success': False, 'error': f"Failed to save edge {edge_data.get('edge_id')}: {result['error']}"}
        
        deleted_count = len(deleted_node_ids or []) + len(deleted_edge_ids or [])
        print(f"[@db:navigation_trees:save_tree_data] Batch deleted {deleted_count} items, saved {len(saved_nodes)} nodes and {len(saved_edges)} edges for tree {tree_id}")
        
        # NOTE: Cache invalidation moved to caller (save_tree_data_api) to avoid duplicate clears
        
        return {
            'success': True,
            'nodes': saved_nodes,
            'edges': saved_edges
        }
    except Exception as e:
        print(f"[@db:navigation_trees:save_tree_data] Error: {e}")
        return {'success': False, 'error': str(e)}

def _get_full_trees_batch(tree_ids: List[str], team_id: str) -> Dict[str, Dict]:
    """{tree_id: full_tree_data} for many trees in ONE round trip.

    Reads mv_full_navigation_trees directly instead of calling the
    get_full_tree_from_mv RPC once per tree. Same payload per tree
    ({success, tree, nodes, edges}) — the RPC just selects this column.

    Every DB call is a WAN hop from a remote host (~200ms), so per-tree reads
    cost ~N*200ms; batching keeps a whole hierarchy to a single round trip.
    """
    if not tree_ids:
        return {}

    supabase = get_supabase()
    out: Dict[str, Dict] = {}
    CHUNK = 100  # bound the URL length on very large hierarchies
    for i in range(0, len(tree_ids), CHUNK):
        result = supabase.table('mv_full_navigation_trees')\
            .select('tree_id,full_tree_data')\
            .in_('tree_id', tree_ids[i:i + CHUNK])\
            .eq('team_id', team_id)\
            .execute()
        for row in result.data or []:
            out[row['tree_id']] = row['full_tree_data']

    print(f"[@db:navigation_trees:_get_full_trees_batch] ⚡ Retrieved {len(out)}/{len(tree_ids)} trees in {(len(tree_ids) + CHUNK - 1) // CHUNK} query(s)")
    return out

def get_full_tree(tree_id: str, team_id: str) -> Dict:
    """
    Get complete tree data (metadata + nodes + edges) from materialized view.
    
    Uses materialized view for instant reads (~10ms) with automatic refresh on writes.
    Database function returns SETOF JSON (array), so we extract first element.
    
    Performance: ~10ms reads (50x faster than function calls)
    """
    supabase = get_supabase()
    
    # RPC call - PostgreSQL function returns SETOF JSON (array with one element)
    result = supabase.rpc(
        'get_full_tree_from_mv',
        {'p_tree_id': tree_id, 'p_team_id': team_id}
    ).execute()
    
    # Extract tree data - handle both dict (PostgREST v14+) and list (older versions)
    if result.data:
        tree_data = result.data[0] if isinstance(result.data, list) else result.data
        print(f"[@db:navigation_trees:get_full_tree] ⚡ Retrieved tree {tree_id} from materialized view")
        
        return {
            'success': tree_data.get('success', True),
            'tree': tree_data.get('tree'),
            'nodes': tree_data.get('nodes', []),
            'edges': tree_data.get('edges', [])
        }
    else:
        print(f"[@db:navigation_trees:get_full_tree] ERROR: Tree {tree_id} not found in materialized view")
        return {'success': False, 'error': 'Tree not found'}

 