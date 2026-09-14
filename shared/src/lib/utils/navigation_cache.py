"""
Unified Navigation Graph Caching System
Manages in-memory cache of NetworkX graphs for nested tree navigation

CACHE STRATEGY:
- Memory-only cache (no disk persistence)
- Cleared on server restart
- Rebuilt automatically on first use
"""

import networkx as nx
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import sys

# Import cache config from shared
from shared.src.lib.config.constants import CACHE_CONFIG
CACHE_TTL = CACHE_CONFIG['LONG_TTL']  # 1 hour

# Unified graph caching for nested trees (memory-only, cleared on restart).
#
# Cache key includes the active variant scope. Two different variants on the
# same tree can have completely different `action_sets`/`verifications` per
# the full-override model (docs/agent/navigation/VARIANT.md), so they need independent
# cached graphs. `None` is the base scope (no variant overrides applied).
_unified_graphs_cache: Dict[str, nx.DiGraph] = {}      # Unified graphs with nested trees
_tree_hierarchy_cache: Dict[str, Dict] = {}            # Tree hierarchy metadata
_node_location_cache: Dict[str, str] = {}              # node_id -> tree_id mapping
_unified_cache_timestamps: Dict[str, datetime] = {}
_root_tree_id_cache: Dict[str, str] = {}               # f"{tree_id}_{team_id}" -> root_tree_id

_VARIANT_BASE_KEY = '__base__'                         # sentinel in cache key for base run


def _variant_key(variant: Optional[str]) -> str:
    """Return the cache-key suffix for a variant scope. None / '' / 'base' → base.

    Treats the literal string 'base' as the base scope: 'base' is a UI label
    for "no variant" (no row exists in userinterface_variants named 'base'),
    and some callers (env DEVICE{i}_VARIANT=base, an explicit `--variant base`
    on the CLI) end up flowing it down here as a string. Mapping it to the
    `__base__` sentinel keeps the cache keyed consistently regardless of
    spelling, so a base run populated under None lines up with later lookups
    under "base".

    Composition: the value may be a multi-variant selection (a '+'/','-separated
    string or a list, e.g. 'no-tvshop+active-standby'). It is canonicalized
    (lowercased, components sorted, '+'-joined) so that every reader and the
    writer land on the SAME key regardless of the order/separator the caller
    used — the cached graph is identical for any ordering of the same set.
    """
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    canonical = canonical_variant_name(variant)
    if not canonical:
        return _VARIANT_BASE_KEY
    return canonical


# root_tree_id -> userinterface_id is immutable (a tree never changes UI), so this is
# memoized forever. The variant name->id map is fetched FRESH per variant cache-key
# (the rare path) so a rename is reflected immediately — no stale memo to invalidate.
_tree_ui_memo: Dict[str, Optional[str]] = {}


def _resolve_variant_id_scope(root_tree_id: str, team_id: str, variant: Optional[str]) -> Optional[str]:
    """Rename-stable cache scope: resolve the variant NAME selection to a canonical
    sorted '+'-joined list of variant *ids*.

    Base runs (no variant — the common path) return None with NO DB call. For a
    variant run, falls back to the canonical NAME string if the UI or any variant id
    can't be resolved, so the cache degrades to its prior name-based behavior rather
    than ever breaking. Keying by id means a variant rename never invalidates the
    cached graph (id is stable; the overrides move with the row).
    """
    from shared.src.lib.utils.navigation_graph import parse_variant_list, canonical_variant_name
    components = parse_variant_list(variant)
    if not components:
        return None  # base run — no resolution, no DB
    name_scope = canonical_variant_name(variant)  # safe fallback
    try:
        ui_id = _tree_ui_memo.get(root_tree_id)
        if ui_id is None and root_tree_id not in _tree_ui_memo:
            from shared.src.lib.utils.supabase_utils import get_supabase_client
            sb = get_supabase_client()
            res = sb.table('navigation_trees').select('userinterface_id').eq('id', root_tree_id).limit(1).execute()
            ui_id = res.data[0].get('userinterface_id') if res.data else None
            _tree_ui_memo[root_tree_id] = ui_id
        if not ui_id:
            return name_scope
        from shared.src.lib.database.userinterface_db import list_variants
        name_to_id = {v['name']: v.get('id') for v in list_variants(team_id, ui_id)}
        ids = []
        for c in components:
            vid = name_to_id.get(c)
            if not vid:
                return name_scope  # unknown component → safe name-based key
            ids.append(vid)
        return '+'.join(sorted(ids))
    except Exception as e:
        print(f"[@navigation:cache:_resolve_variant_id_scope] fallback to name ({e})")
        return name_scope


def _make_cache_key(root_tree_id: str, team_id: str, variant: Optional[str]) -> str:
    """Canonical cache key `unified_{root}_{team}_{scope}`.

    The variant scope is keyed by stable variant *ids* (not names), so a variant
    rename never invalidates the cached graph. Base runs use the `__base__` sentinel.
    """
    scope = _resolve_variant_id_scope(root_tree_id, team_id, variant)
    return f"unified_{root_tree_id}_{team_id}_{scope or _VARIANT_BASE_KEY}"


def _matching_variant_keys(root_tree_id: str, team_id: str):
    """Iterate all current cache keys that belong to (root_tree_id, team_id)
    regardless of variant scope. Used by invalidation helpers that must drop
    every variant graph when the base data underneath changes.
    """
    prefix = f"unified_{root_tree_id}_{team_id}_"
    return [k for k in list(_unified_graphs_cache.keys()) if k.startswith(prefix)]


def _invalidate_non_base_variant_entries(root_tree_id: str, team_id: str) -> int:
    """Drop every variant cache entry for this tree EXCEPT base. Called after
    an incremental base-row mutation: variant graphs that fall through to
    base would otherwise serve stale content. Returns number of keys dropped.
    """
    base_key = _make_cache_key(root_tree_id, team_id, None)
    dropped = 0
    for key in _matching_variant_keys(root_tree_id, team_id):
        if key == base_key:
            continue
        if key in _unified_graphs_cache:
            del _unified_graphs_cache[key]
            dropped += 1
        _unified_cache_timestamps.pop(key, None)
        _tree_hierarchy_cache.pop(key, None)
    if dropped:
        print(f"[@navigation:cache:_invalidate_non_base_variant_entries] Dropped {dropped} variant entries for tree {root_tree_id} (base row mutated)")
    return dropped


def _resolve_root_tree_id(tree_id: str, team_id: str) -> Optional[str]:
    """Resolve subtree id → root id (memoized).

    Edge Run / Node Run / pathfinding all take a request `tree_id` that can
    be a subtree, but `populate_unified_cache` only stores under the root.
    Without this, callers passing a subtree id silently miss the cache.
    DB lookup is one shot per (tree_id, team_id) per host lifetime.
    """
    cache_key = f"{tree_id}_{team_id}"
    if cache_key in _root_tree_id_cache:
        return _root_tree_id_cache[cache_key]
    try:
        from shared.src.lib.database.navigation_trees_db import _get_root_tree_id
        root_id = _get_root_tree_id(tree_id, team_id)
    except Exception as e:
        print(f"[@navigation:cache:_resolve_root_tree_id] Error: {e}")
        return None
    if root_id:
        _root_tree_id_cache[cache_key] = root_id
    return root_id


def get_cached_unified_graph(
    root_tree_id: str,
    team_id: str,
    variant: Optional[str] = None,
    silent: bool = False,
) -> Optional[nx.DiGraph]:
    """
    Get cached unified NetworkX graph - memory-only (no file persistence).

    Accepts either the root tree id or any subtree id. Cache is keyed under
    the root + variant scope (see `populate_unified_cache`); subtree ids are
    resolved via DB and memoized so reads use the same key the writer used.

    `variant=None` (or empty string) is the base scope.
    """
    if not root_tree_id or not team_id:
        return None

    cache_key = _make_cache_key(root_tree_id, team_id, variant)

    # Direct hit (root id, or already-resolved subtree id).
    if cache_key in _unified_graphs_cache:
        timestamp = _unified_cache_timestamps.get(cache_key)
        if timestamp:
            age = (datetime.now() - timestamp).total_seconds()
            if age < CACHE_TTL:
                if not silent:
                    print(f"[@navigation:cache:get_cached_unified_graph] ✅ Memory Cache HIT: {cache_key} (age: {age:.1f}s)")
                return _unified_graphs_cache[cache_key]
            else:
                del _unified_graphs_cache[cache_key]
                del _unified_cache_timestamps[cache_key]
                if not silent:
                    print(f"[@navigation:cache:get_cached_unified_graph] Cache expired, removed: {cache_key}")

    # Miss on the raw id. Resolve subtree → root and retry.
    resolved_root = _resolve_root_tree_id(root_tree_id, team_id)
    if resolved_root and resolved_root != root_tree_id:
        resolved_key = _make_cache_key(resolved_root, team_id, variant)
        if resolved_key in _unified_graphs_cache:
            timestamp = _unified_cache_timestamps.get(resolved_key)
            if timestamp and (datetime.now() - timestamp).total_seconds() < CACHE_TTL:
                if not silent:
                    age = (datetime.now() - timestamp).total_seconds()
                    print(f"[@navigation:cache:get_cached_unified_graph] ✅ Memory Cache HIT (subtree→root: {root_tree_id} → {resolved_root}, variant={_variant_key(variant)}, age: {age:.1f}s)")
                return _unified_graphs_cache[resolved_key]

    return None

def refresh_cache_timestamp(
    root_tree_id: str,
    team_id: str,
    variant: Optional[str] = None,
) -> bool:
    """
    Refresh the timestamp for an existing cache entry to prevent TTL expiry.

    Args:
        root_tree_id: Root navigation tree ID
        team_id: Team ID for security
        variant: Variant scope (None / '' = base)

    Returns:
        True if timestamp was refreshed, False if cache doesn't exist
    """
    cache_key = _make_cache_key(root_tree_id, team_id, variant)

    if cache_key in _unified_graphs_cache:
        _unified_cache_timestamps[cache_key] = datetime.now()
        print(f"[@navigation:cache:refresh_cache_timestamp] Refreshed timestamp for {cache_key}")
        return True

    return False

def populate_unified_cache(
    root_tree_id: str,
    team_id: str,
    all_trees_data: List[Dict],
    variant_node_overrides: Optional[Dict] = None,
    variant_edge_overrides: Optional[Dict] = None,
    variant: Optional[str] = None,
) -> Optional[nx.DiGraph]:
    """
    Build and cache unified graph - memory-only (no file persistence).
    CRITICAL: Always stores under the ROOT tree_id + variant scope.

    Args:
        variant_node_overrides: Optional variant `node_overrides` map for resolution.
            None means base behaviour — only `hidden_in_base` rows are skipped.
        variant_edge_overrides: Optional variant `edge_overrides` map for resolution.
        variant: Variant scope name (None / '' = base). Must match the overrides
            supplied — used only for the cache key, not for resolution.
    """
    try:
        from shared.src.lib.utils.navigation_graph import create_unified_networkx_graph

        if not all_trees_data:
            return None

        # STEP 1: Find the actual root tree from the hierarchy
        actual_root_tree_id = root_tree_id
        for tree_data in all_trees_data:
            tree_info = tree_data.get('tree_info', {})
            if tree_info.get('is_root_tree', False):
                actual_root_tree_id = tree_data.get('tree_id')
                print(f"[@navigation:cache:populate_unified_cache] Found root tree: {actual_root_tree_id}")
                break

        # STEP 2: Use root tree_id + variant scope as cache key.
        cache_key = _make_cache_key(actual_root_tree_id, team_id, variant)

        # STEP 3: Build unified graph from all trees (variant resolution per tree)
        unified_graph = create_unified_networkx_graph(
            all_trees_data,
            variant_node_overrides=variant_node_overrides,
            variant_edge_overrides=variant_edge_overrides,
        )
        if not unified_graph:
            return None

        # STEP 4: Store in memory cache keyed by (root_tree, team, variant)
        _unified_graphs_cache[cache_key] = unified_graph
        _unified_cache_timestamps[cache_key] = datetime.now()

        print(f"[@navigation:cache:populate_unified_cache] ✅ Cached to memory: {cache_key}")
        print(f"[@navigation:cache:populate_unified_cache] Graph: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")
        print(f"[@navigation:cache:populate_unified_cache] Trees in hierarchy: {len(all_trees_data)}")
        return unified_graph

    except Exception as e:
        print(f"[@navigation:cache:populate_unified_cache] Error: {e}")
        return None

def save_unified_cache(
    root_tree_id: str,
    team_id: str,
    graph: nx.DiGraph,
    variant: Optional[str] = None,
) -> bool:
    """
    Save existing unified graph to memory cache (incremental update).

    Accepts either root or subtree id; resolves to root so the writer key
    matches the populate-side key (`populate_unified_cache` only ever
    stores under the root). Without this, an incremental update routed
    through a subtree id would create a duplicate entry under the subtree
    key while the actual graph stayed under the root key.

    `variant=None` (or empty string) is the base scope.
    """
    resolved_root = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id
    cache_key = _make_cache_key(resolved_root, team_id, variant)

    try:
        # Store in memory cache only (cleared on restart)
        _unified_graphs_cache[cache_key] = graph
        _unified_cache_timestamps[cache_key] = datetime.now()

        if resolved_root != root_tree_id:
            print(f"[@navigation:cache:save_unified_cache] ✅ Saved graph to memory: {cache_key} (resolved subtree {root_tree_id} → root) ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
        else:
            print(f"[@navigation:cache:save_unified_cache] ✅ Saved graph to memory: {cache_key} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
        return True

    except Exception as e:
        print(f"[@navigation:cache:save_unified_cache] Error: {e}")
        return False

# ============================================================================
# INCREMENTAL CACHE UPDATE FUNCTIONS
# ============================================================================

def update_edge_in_cache(root_tree_id: str, team_id: str, edge_data: Dict) -> bool:
    """
    Update or add an edge directly in the cached graph (no rebuild needed)
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        edge_data: Edge data with source_node_id, target_node_id, action_sets, etc.
    
    Returns:
        True if updated successfully
    """
    try:
        # Get cached graph
        graph = get_cached_unified_graph(root_tree_id, team_id)
        if not graph:
            print(f"[@navigation:cache:update_edge_in_cache] No cache found, cannot update incrementally")
            return False
        
        source_id = edge_data.get('source_node_id')
        target_id = edge_data.get('target_node_id')
        
        if not source_id or not target_id:
            print(f"[@navigation:cache:update_edge_in_cache] Missing source or target node ID")
            return False
        
        # Check if nodes exist
        if source_id not in graph.nodes or target_id not in graph.nodes:
            print(f"[@navigation:cache:update_edge_in_cache] Source or target node not in graph")
            return False
        
        # Update or add edge with all attributes.
        # Per-direction final_wait_time + threshold ride along inside action_sets.
        graph.add_edge(source_id, target_id, **{
            'edge_id': edge_data.get('edge_id'),
            'action_sets': edge_data.get('action_sets', []),
            'default_action_set_id': edge_data.get('default_action_set_id'),
            'label': edge_data.get('label', ''),
            'tree_id': edge_data.get('tree_id'),
            'data': edge_data.get('data', {}),
        })
        
        # Save updated graph back to cache
        save_unified_cache(root_tree_id, team_id, graph)
        # Base row mutated → drop variant cache entries that fall through to base.
        resolved_root_for_invalidate = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id
        _invalidate_non_base_variant_entries(resolved_root_for_invalidate, team_id)
        
        # Clear, identifiable log
        print(f"\n{'='*80}")
        print(f"[@navigation:cache:update_edge_in_cache] ✅ INCREMENTAL UPDATE: Edge {edge_data.get('edge_id')}")
        print(f"  → Cache key: unified_{root_tree_id}_{team_id}")
        print(f"  → Route: {source_id} → {target_id}")
        print(f"  → Label: {edge_data.get('label', 'N/A')}")
        action_sets = edge_data.get('action_sets', [])
        if action_sets:
            print(f"  → Action sets updated: {len(action_sets)} sets")
            for idx, action_set in enumerate(action_sets[:2]):  # Show first 2
                direction = action_set.get('direction', 'forward')
                actions_count = len(action_set.get('actions', []))
                print(f"     [{idx+1}] {direction}: {actions_count} actions")
        print(f"{'='*80}\n")
        return True
        
    except Exception as e:
        print(f"[@navigation:cache:update_edge_in_cache] Error: {e}")
        return False

def delete_edge_from_cache(root_tree_id: str, team_id: str, source_id: str, target_id: str) -> bool:
    """
    Delete an edge directly from the cached graph (no rebuild needed)
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        source_id: Source node ID
        target_id: Target node ID
    
    Returns:
        True if deleted successfully
    """
    try:
        graph = get_cached_unified_graph(root_tree_id, team_id)
        if not graph:
            print(f"[@navigation:cache:delete_edge_from_cache] No cache found")
            return False
        
        if graph.has_edge(source_id, target_id):
            graph.remove_edge(source_id, target_id)
            save_unified_cache(root_tree_id, team_id, graph)
            # Base row mutated → drop variant cache entries that fall through to base.
            resolved_root_for_invalidate = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id
            _invalidate_non_base_variant_entries(resolved_root_for_invalidate, team_id)
            print(f"[@navigation:cache:delete_edge_from_cache] ✅ Deleted edge {source_id} → {target_id}")
            return True
        else:
            print(f"[@navigation:cache:delete_edge_from_cache] Edge not found in graph")
            return False
            
    except Exception as e:
        print(f"[@navigation:cache:delete_edge_from_cache] Error: {e}")
        return False

def update_node_in_cache(root_tree_id: str, team_id: str, node_data: Dict) -> bool:
    """
    Update or add a node directly in the cached graph (no rebuild needed)
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        node_data: Node data with node_id, label, verifications, etc.
    
    Returns:
        True if updated successfully
    """
    try:
        graph = get_cached_unified_graph(root_tree_id, team_id)
        if not graph:
            print(f"[@navigation:cache:update_node_in_cache] No cache found")
            return False
        
        node_id = node_data.get('node_id')
        if not node_id:
            print(f"[@navigation:cache:update_node_in_cache] Missing node_id")
            return False
        
        # Get existing node attributes if node exists, otherwise start fresh
        if node_id in graph.nodes:
            existing_attrs = graph.nodes[node_id].copy()
        else:
            existing_attrs = {}
        
        # Update only the fields that are provided in node_data
        if 'label' in node_data:
            existing_attrs['label'] = node_data['label']
        if 'node_type' in node_data:
            existing_attrs['node_type'] = node_data['node_type']
        if 'verifications' in node_data:
            existing_attrs['verifications'] = node_data['verifications']
        if 'tree_id' in node_data:
            existing_attrs['tree_id'] = node_data['tree_id']
        if 'data' in node_data:
            existing_attrs['data'] = node_data['data']
        
        # Update node with merged attributes
        graph.add_node(node_id, **existing_attrs)
        
        save_unified_cache(root_tree_id, team_id, graph)
        # Base row mutated → drop variant cache entries that fall through to base.
        resolved_root_for_invalidate = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id
        _invalidate_non_base_variant_entries(resolved_root_for_invalidate, team_id)
        
        # Clear, identifiable log
        print(f"\n{'='*80}")
        print(f"[@navigation:cache:update_node_in_cache] ✅ INCREMENTAL UPDATE: Node {node_id}")
        print(f"  → Cache key: unified_{root_tree_id}_{team_id}")
        print(f"  → Label: {existing_attrs.get('label')}")
        if 'verifications' in node_data:
            print(f"  → Verifications updated: {len(node_data.get('verifications', []))} verifications")
            for idx, v in enumerate(node_data.get('verifications', [])[:3]):  # Show first 3
                v_type = v.get('verification_type', 'unknown')
                params = v.get('params', {})
                threshold = params.get('threshold', 'N/A')
                ref_name = params.get('reference_name', 'N/A')
                print(f"     [{idx+1}] {v_type}: {ref_name} (threshold: {threshold})")
        print(f"{'='*80}\n")
        return True
        
    except Exception as e:
        print(f"[@navigation:cache:update_node_in_cache] Error: {e}")
        return False

def delete_node_from_cache(root_tree_id: str, team_id: str, node_id: str) -> bool:
    """
    Delete a node directly from the cached graph (no rebuild needed)
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID
        node_id: Node ID to delete
    
    Returns:
        True if deleted successfully
    """
    try:
        graph = get_cached_unified_graph(root_tree_id, team_id)
        if not graph:
            print(f"[@navigation:cache:delete_node_from_cache] No cache found")
            return False
        
        if node_id in graph.nodes:
            graph.remove_node(node_id)  # This also removes connected edges
            save_unified_cache(root_tree_id, team_id, graph)
            # Base row mutated → drop variant cache entries that fall through to base.
            resolved_root_for_invalidate = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id
            _invalidate_non_base_variant_entries(resolved_root_for_invalidate, team_id)
            print(f"[@navigation:cache:delete_node_from_cache] ✅ Deleted node {node_id}")
            return True
        else:
            print(f"[@navigation:cache:delete_node_from_cache] Node not found in graph")
            return False
            
    except Exception as e:
        print(f"[@navigation:cache:delete_node_from_cache] Error: {e}")
        return False

def get_node_tree_location(node_id: str, root_tree_id: str, team_id: str) -> Optional[str]:
    """
    Get which tree a node belongs to in the unified hierarchy
    
    Args:
        node_id: Node ID to locate
        root_tree_id: Root tree ID for the hierarchy
        team_id: Team ID for security
        
    Returns:
        Tree ID containing the node or None if not found
    """
    location_cache_key = f"locations_{root_tree_id}_{team_id}"
    node_location_map = _node_location_cache.get(location_cache_key, {})
    return node_location_map.get(node_id)

def get_tree_hierarchy_metadata(root_tree_id: str, team_id: str) -> Optional[Dict]:
    """
    Get tree hierarchy metadata for the unified cache
    
    Args:
        root_tree_id: Root tree ID
        team_id: Team ID for security
        
    Returns:
        Dictionary of tree hierarchy metadata or None if not cached
    """
    hierarchy_cache_key = f"hierarchy_{root_tree_id}_{team_id}"
    return _tree_hierarchy_cache.get(hierarchy_cache_key)

def get_node_from_graph(node_id: str, root_tree_id: str, team_id: str) -> Optional[Dict]:
    """
    Get node data from unified graph cache (ZERO database calls!)
    
    Args:
        node_id: Node ID to retrieve
        root_tree_id: Root tree ID for the hierarchy
        team_id: Team ID for security
        
    Returns:
        Dict with node data or None if not found
    """
    try:
        unified_graph = get_cached_unified_graph(root_tree_id, team_id)
        if not unified_graph:
            print(f"[@navigation:cache:get_node_from_graph] No cached graph for tree {root_tree_id}")
            return None
        
        if node_id not in unified_graph.nodes:
            print(f"[@navigation:cache:get_node_from_graph] Node {node_id} not found in graph")
            return None
        
        # Get all node attributes from graph
        node_attrs = unified_graph.nodes[node_id]
        
        # Return in same format as database for compatibility
        return {
            'node_id': node_id,
            'label': node_attrs.get('label', ''),
            'node_type': node_attrs.get('node_type', 'screen'),
            'tree_id': node_attrs.get('tree_id'),
            'tree_name': node_attrs.get('tree_name', ''),
            'tree_depth': node_attrs.get('tree_depth', 0),
            'verifications': node_attrs.get('verifications', []),
            'verification_pass_condition': node_attrs.get('metadata', {}).get('verification_pass_condition', 'all'),
            'data': node_attrs.get('metadata', {}),
            'is_entry_point': node_attrs.get('is_entry_point', False),
        }
    except Exception as e:
        print(f"[@navigation:cache:get_node_from_graph] Error: {e}")
        return None

def clear_unified_cache(
    root_tree_id: str = None,
    team_id: str = None,
    variant: Optional[str] = None,
):
    """Clear memory cache (memory-only, cleared on restart).

    Accepts either the root tree id or any subtree id. The cache is keyed
    under (root, team, variant); a subtree-id call resolves up first or
    it silently no-ops. Resolution is memoized in `_root_tree_id_cache`.

    When `variant` is None (the default), drops ALL variant entries for
    this tree — used after a base-row mutation that may invalidate every
    variant that falls through. To clear only one variant pass its name.
    """
    if root_tree_id and team_id:
        # Resolve subtree → root so save-handler clears (which pass the
        # currently-edited subtree id) actually hit the cached graph.
        resolved = _resolve_root_tree_id(root_tree_id, team_id) or root_tree_id

        # Build the set of keys to clear. If a variant is explicitly named, only
        # that variant entry is dropped; otherwise we drop every variant entry
        # for the tree (base mutations affect fall-through views).
        keys_to_clear = set()
        if variant is None:
            keys_to_clear.update(_matching_variant_keys(root_tree_id, team_id))
            if resolved != root_tree_id:
                keys_to_clear.update(_matching_variant_keys(resolved, team_id))
        else:
            keys_to_clear.add(_make_cache_key(root_tree_id, team_id, variant))
            if resolved != root_tree_id:
                keys_to_clear.add(_make_cache_key(resolved, team_id, variant))

        cleared_any = False
        for cache_key in keys_to_clear:
            if cache_key in _unified_graphs_cache:
                del _unified_graphs_cache[cache_key]
                cleared_any = True
            if cache_key in _unified_cache_timestamps:
                del _unified_cache_timestamps[cache_key]
            if cache_key in _tree_hierarchy_cache:
                del _tree_hierarchy_cache[cache_key]

        if cleared_any:
            scope_label = 'all variants' if variant is None else f"variant={_variant_key(variant)}"
            if resolved != root_tree_id:
                print(f"[@navigation:cache:clear_unified_cache] Cleared memory cache for tree: {root_tree_id} (resolved subtree → root {resolved}, {scope_label}, {len(keys_to_clear)} keys)")
            else:
                print(f"[@navigation:cache:clear_unified_cache] Cleared memory cache for tree: {root_tree_id} ({scope_label}, {len(keys_to_clear)} keys)")
        else:
            print(f"[@navigation:cache:clear_unified_cache] No cached graph for tree: {root_tree_id} (resolved={resolved}, variant={_variant_key(variant) if variant is not None else 'all'}) — nothing to clear")
    else:
        # Clear all in-memory caches
        _unified_graphs_cache.clear()
        _unified_cache_timestamps.clear()
        _tree_hierarchy_cache.clear()
        _node_location_cache.clear()
        _root_tree_id_cache.clear()

        print(f"[@navigation:cache:clear_unified_cache] Cleared ALL memory caches")

def get_cache_stats() -> Dict[str, int]:
    """Get cache statistics from memory"""
    return {
        'cache_type': 'Memory (cleared on restart)',
        'cached_graphs': len(_unified_graphs_cache),
        'cache_timestamps': len(_unified_cache_timestamps)
    }

# Backward compatibility aliases (deprecated - use unified functions directly)
def get_cached_graph(tree_id: str, team_id: str, force_rebuild: bool = False) -> Optional[nx.DiGraph]:
    """
    DEPRECATED: Use get_cached_unified_graph instead
    Backward compatibility wrapper for legacy code
    """
    print(f"⚠️  [@navigation:cache:get_cached_graph] DEPRECATED: Use get_cached_unified_graph instead")
    return get_cached_unified_graph(tree_id, team_id)

def populate_cache(tree_id: str, team_id: str, nodes: List[Dict], edges: List[Dict]) -> Optional[nx.DiGraph]:
    """
    DEPRECATED: Use populate_unified_cache instead
    Backward compatibility wrapper for legacy code
    """
    print(f"⚠️  [@navigation:cache:populate_cache] DEPRECATED: Use populate_unified_cache instead")
    
    # Convert single tree to unified format
    tree_data_for_unified = [{
        'tree_id': tree_id,
        'tree_info': {
            'name': f'Tree {tree_id}',
            'is_root_tree': True,
            'tree_depth': 0,
            'parent_tree_id': None,
            'parent_node_id': None
        },
        'nodes': nodes,
        'edges': edges
    }]
    
    return populate_unified_cache(tree_id, team_id, tree_data_for_unified)