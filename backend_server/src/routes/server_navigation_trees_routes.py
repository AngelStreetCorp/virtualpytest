"""
Navigation Trees API Routes - Normalized Architecture

New API structure for normalized navigation tables:
- Tree metadata operations
- Individual node operations  
- Individual edge operations
- Batch operations
- Nested tree operations

Clean, scalable REST endpoints without monolithic JSONB operations.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.database.navigation_trees_db import (
    # Tree metadata operations
    get_all_trees, get_tree_metadata, save_tree_metadata, delete_tree,
    # Node operations
    get_tree_nodes, get_node_by_id, resolve_node, save_node, delete_node,
    # Edge operations
    get_tree_edges, get_edge_by_id, save_edge, delete_edge,
    # Batch operations
    save_tree_data, get_full_tree,
    # Interface operations
    get_root_tree_for_interface,
    # Nested tree operations
    get_node_sub_trees, create_sub_tree, get_tree_hierarchy,
    get_tree_breadcrumb, delete_tree_cascade, move_subtree,
    # History operations
    get_tree_history, restore_tree_from_history
)
from shared.src.lib.database.userinterface_db import (
    get_all_userinterfaces,
)
from shared.src.lib.utils.app_utils import DEFAULT_USER_ID, check_supabase
from shared.src.lib.config.constants import CACHE_CONFIG
import time
import threading
from typing import Optional

server_navigation_trees_bp = Blueprint('server_navigation_trees', __name__, url_prefix='/server')

# ============================================================================
# IN-MEMORY CACHE FOR NAVIGATION TREES (reduces DB queries from 3 to 0)
# ============================================================================

_tree_cache = {}  # {tree_id: {'data': {...}, 'timestamp': time.time()}}
_cache_lock = threading.Lock()

def get_cached_tree(tree_id: str, team_id: str):
    """Get tree from cache if available and not expired."""
    with _cache_lock:
        cache_key = f"{team_id}:{tree_id}"
        if cache_key in _tree_cache:
            cached = _tree_cache[cache_key]
            age = time.time() - cached['timestamp']
            if age < CACHE_CONFIG['MEDIUM_TTL']:
                print(f"[@cache] HIT: Tree {tree_id} (age: {age:.1f}s)")
                return cached['data']
            else:
                # Expired
                print(f"[@cache] EXPIRED: Tree {tree_id} (age: {age:.1f}s)")
                del _tree_cache[cache_key]
        return None

def set_cached_tree(tree_id: str, team_id: str, data):
    """Store tree in cache."""
    with _cache_lock:
        cache_key = f"{team_id}:{tree_id}"
        _tree_cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }
        print(f"[@cache] SET: Tree {tree_id} (total cached: {len(_tree_cache)})")

def invalidate_cached_tree(tree_id: str, team_id: str, propagate_to_hosts: bool = True):
    """Invalidate cached tree when it's modified.

    Always clears the local server caches (`_tree_cache` HTTP response cache +
    shared `invalidate_navigation_cache_for_tree`).

    When ``propagate_to_hosts`` is True (default), also wipes the host-side
    unified NetworkX graph on every host. That wipe is fine for structural
    changes (create/delete/restore/bulk save) but **destructive** for value
    edits: the frontend follows up with `/cache/update-node` /
    `/cache/update-edge` to patch the graph in place, and `update_*_in_cache`
    bails when the cache is empty — which loses the patch and leaves the host
    with an empty graph until the next take-control. Pass ``False`` for
    update endpoints that already have a granular incremental update.
    """
    # Clear SERVER cache
    with _cache_lock:
        cache_key = f"{team_id}:{tree_id}"
        if cache_key in _tree_cache:
            del _tree_cache[cache_key]
            print(f"[@cache] INVALIDATE: Tree {tree_id}")

    # Drop any KPI action-set cache entry whose hierarchy contained this tree.
    _invalidate_kpi_action_sets_for_tree(tree_id)
    # Same idea for the node-label list backing the goto-script picker.
    _invalidate_navigation_nodes_for_tree(tree_id)

    # Clear server-local shared cache
    from shared.src.lib.database.navigation_trees_db import invalidate_navigation_cache_for_tree
    invalidate_navigation_cache_for_tree(tree_id, team_id)

    if not propagate_to_hosts:
        return

    # Propagate to ALL HOST VMs in the background — clears unified graph + preview cache.
    # Run async so the API response isn't blocked on N synchronous host HTTP calls.
    # Under gevent (monkey-patched), threading.Thread becomes a greenlet, so this
    # cooperates with the request loop instead of forking an OS thread.
    def _propagate_host_cache_clear():
        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager
            from backend_server.src.lib.utils.route_utils import proxy_to_host_direct

            host_manager = get_host_manager()
            hosts = host_manager.get_all_hosts()
            cleared = []
            for host_info in hosts.values():
                try:
                    result, _ = proxy_to_host_direct(
                        host_info,
                        f'/host/navigation/cache/clear/{tree_id}?team_id={team_id}',
                        'POST',
                    )
                    if result and result.get('success'):
                        cleared.append(host_info.get('host_name'))
                except Exception:
                    pass  # Per-host failure is non-fatal
            if cleared:
                print(f"[@cache] INVALIDATE HOST: Tree {tree_id} — cache cleared on {', '.join(cleared)}")
            else:
                print(f"[@cache] INVALIDATE HOST: Tree {tree_id} — no hosts had cache to clear")
        except Exception as e:
            print(f"[@cache] INVALIDATE HOST: Tree {tree_id} — propagation failed: {e}")

    import threading
    threading.Thread(target=_propagate_host_cache_clear, daemon=True).start()


def _fetch_tree_metrics(tree_id: str, team_id: str, variant: str = None):
    """
    Internal helper to fetch metrics for a tree (used by combined endpoint).
    Uses optimized Supabase function that reads from pre-aggregated metrics tables.
    Returns metrics data or None on error.

    Performance: ~5ms (reads from node_metrics and edge_metrics tables)

    `variant` is the run scope filter: NULL = base-only, otherwise the lowercase
    variant name. The aggregate tables key per scope so each variant gets its
    own averages — base runs never average together with variant runs.
    """
    from shared.src.lib.utils.supabase_utils import get_supabase_client

    supabase = get_supabase_client()

    # Call optimized Supabase function (reads from pre-aggregated metrics tables)
    # This is MUCH faster than computing from execution_results
    result = supabase.rpc(
        'get_tree_metrics_optimized',
        {'p_tree_id': tree_id, 'p_team_id': team_id, 'p_variant': variant}
    ).execute()

    if result.data:
        metrics_data = result.data[0] if isinstance(result.data, list) else result.data
        print(f"[@metrics] ⚡ Fetched pre-aggregated metrics for tree {tree_id} (variant={variant or 'base'})")

        return {
            'nodes': metrics_data.get('nodes', {}),
            'edges': metrics_data.get('edges', {}),
            'variant': variant,
            'global_confidence': metrics_data.get('global_confidence', 0.0),
            'confidence_distribution': metrics_data.get('confidence_distribution', {
                'high': 0, 'medium': 0, 'low': 0, 'untested': 0
            }),
            'hierarchy_info': {
                'total_trees': 1,
                'max_depth': 0,
                'has_nested_trees': False,
                'trees': [{
                    'tree_id': tree_id,
                    'name': 'Navigation Tree',
                    'depth': 0,
                    'is_root': True
                }]
            }
        }
    else:
        print(f"[@metrics] No metrics data returned for tree {tree_id} (variant={variant or 'base'})")
        return None


# ============================================================================
# KPI ACTION-SET CACHE (drives the kpi_measurement script's edge picker)
# ============================================================================
# Cache key: (team_id, userinterface_name). Each entry stores the computed
# action-set list and the set of tree_ids that fed it, so a single edge edit
# anywhere in the hierarchy can target the right entries for eviction.
# Auto-invalidated via _invalidate_kpi_action_sets_for_tree(), called from
# invalidate_cached_tree() so node/edge/tree writes drop matching entries.

_kpi_action_sets_cache = {}
_kpi_cache_lock = threading.Lock()


def _invalidate_kpi_action_sets_for_tree(tree_id: str):
    with _kpi_cache_lock:
        to_drop = [k for k, v in _kpi_action_sets_cache.items()
                   if tree_id in v.get('tree_ids', ())]
        for k in to_drop:
            del _kpi_action_sets_cache[k]
        if to_drop:
            print(f"[@cache] INVALIDATE KPI: {len(to_drop)} entries for tree {tree_id}")


def _resolve_variant_overrides(userinterface_id: str, team_id: str, variant: Optional[str]):
    """Gather the applied override maps for a variant SELECTION — a single
    name OR a '+'/','-separated composition (see docs/agent/navigation/VARIANT.md
    "Composition"). Used by both picker compute functions so they apply the
    same resolution semantics the runtime graph builder uses.

    Returns (scope_bundle_or_None, error_or_None). The bundle is None for base
    scope. The final merged maps are produced by _compose_scope_overrides()
    once the tree hierarchy is loaded, because compose needs the
    hidden_in_base ids from EVERY tree (variant-only rows can live in
    subtrees) — mirrors navigation_executor_tree_manager step 5b. An unknown
    component surfaces as an error so the endpoint can 404 instead of
    silently falling through to base.
    """
    from shared.src.lib.utils.navigation_graph import parse_variant_list
    components = parse_variant_list(variant)
    if not components:
        return None, None
    from shared.src.lib.database.userinterface_db import list_variants
    all_variants = list_variants(team_id, userinterface_id)
    by_name = {v['name']: v for v in all_variants}
    missing = [c for c in components if c not in by_name]
    if missing:
        return None, f"unknown variant(s) {missing}"
    # Applied maps in CANONICAL (sorted) order so composition is
    # order-independent and 'last wins' is deterministic.
    applied_node_maps = []
    applied_edge_maps = []
    for name in sorted(components):
        row = by_name[name]
        applied_node_maps.append(row.get('node_overrides') or {})
        applied_edge_maps.append(row.get('edge_overrides') or {})
    # Rows that ANY variant of the UI disables = legacy "disable-on-others"
    # rows; compose needs them for backward-compatible visibility.
    cross_disabled_node_ids = set()
    cross_disabled_edge_ids = set()
    for v in all_variants:
        for rid, entry in (v.get('node_overrides') or {}).items():
            if isinstance(entry, dict) and entry.get('disabled'):
                cross_disabled_node_ids.add(rid)
        for rid, entry in (v.get('edge_overrides') or {}).items():
            if isinstance(entry, dict) and entry.get('disabled'):
                cross_disabled_edge_ids.add(rid)
    return {
        'applied_node_maps': applied_node_maps,
        'applied_edge_maps': applied_edge_maps,
        'cross_disabled_node_ids': cross_disabled_node_ids,
        'cross_disabled_edge_ids': cross_disabled_edge_ids,
    }, None


def _compose_scope_overrides(scope_bundle, trees):
    """Merge a _resolve_variant_overrides() bundle into the single node/edge
    override maps that resolve_node_variant / resolve_edge_variant consume,
    gathering hidden_in_base ids across the whole hierarchy first (same
    pattern as the runtime tree manager). Returns (node_map, edge_map) —
    (None, None) for base scope."""
    if scope_bundle is None:
        return None, None
    from shared.src.lib.utils.navigation_graph import (
        compose_node_overrides,
        compose_edge_overrides,
    )
    hidden_node_ids = set()
    hidden_edge_ids = set()
    for tree in trees:
        for node in tree.get('nodes', []):
            if node.get('hidden_in_base') and node.get('node_id'):
                hidden_node_ids.add(node['node_id'])
        for edge in tree.get('edges', []):
            if edge.get('hidden_in_base') and edge.get('edge_id'):
                hidden_edge_ids.add(edge['edge_id'])
    return (
        compose_node_overrides(
            scope_bundle['applied_node_maps'], hidden_node_ids,
            scope_bundle['cross_disabled_node_ids'],
        ),
        compose_edge_overrides(
            scope_bundle['applied_edge_maps'], hidden_edge_ids,
            scope_bundle['cross_disabled_edge_ids'],
        ),
    )


def _compute_kpi_action_sets(userinterface_name: str, team_id: str, variant: Optional[str] = None):
    """Resolve userinterface → root tree → hierarchy, then filter every
    action_set across the hierarchy down to those that can produce a KPI
    measurement. An action_set qualifies if:
      - kpi_references is a non-empty list, OR
      - use_verifications_for_kpi is True AND the target node has verifications.

    Variant scope (`variant=None` = base) is applied via the same resolvers
    the runtime uses: `resolve_node_variant` / `resolve_edge_variant`. Rows
    disabled in the active scope (variant entry `disabled: true`, or base
    `hidden_in_base: true`) drop out; edges whose endpoint nodes are disabled
    drop with them. Action_sets come from the *resolved* edge so variant
    overrides that replace `action_sets` are honoured.

    Returns ({'action_sets': [...], 'tree_ids': [...]}, None) or (None, error).
    """
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import (
        get_complete_tree_hierarchy,
    )
    from shared.src.lib.utils.navigation_graph import (
        resolve_node_variant, resolve_edge_variant,
    )

    ui = get_userinterface_by_name(userinterface_name, team_id)
    if not ui:
        return None, f"Userinterface '{userinterface_name}' not found"

    scope_bundle, err = _resolve_variant_overrides(ui['id'], team_id, variant)
    if err:
        return None, f"{err} for userinterface '{userinterface_name}'"

    root_tree = get_root_tree_for_interface(ui['id'], team_id)
    if not root_tree:
        return None, f"No root tree for userinterface '{userinterface_name}'"

    hierarchy = get_complete_tree_hierarchy(root_tree['id'], team_id)
    if not hierarchy.get('success'):
        return None, hierarchy.get('error', 'Failed to load tree hierarchy')

    trees = hierarchy.get('all_trees_data') or []
    tree_ids = [t['tree_id'] for t in trees]

    node_overrides, edge_overrides = _compose_scope_overrides(scope_bundle, trees)

    # Index every active node across the hierarchy. Reverse action_sets
    # measure against the SOURCE node, so both endpoints must be present.
    # Verifications come from the variant-resolved row (variant may replace
    # the list, affecting `use_verifications_for_kpi` viability).
    node_lookup = {}
    for tree in trees:
        for node in tree.get('nodes', []):
            resolved_node = resolve_node_variant(node, node_overrides)
            if not resolved_node.get('__variant_state', {}).get('active', True):
                continue
            node_id = resolved_node.get('node_id') or resolved_node.get('id')
            if not node_id:
                continue
            verifs = resolved_node.get('verifications') or []
            node_lookup[node_id] = {
                'label': resolved_node.get('label', ''),
                'has_verifications': len(verifs) > 0,
            }

    # Conditional-sibling KPI intent: forward action_sets that actually OWN
    # actions, keyed by (source, action_set_id). A conditional sibling shares
    # this id with empty actions and borrows the owner's actions at runtime
    # (navigation_graph.create_networkx_graph); for KPI it likewise borrows the
    # owner's `use_verifications_for_kpi` so it can be measured the SAME way —
    # against its OWN target node. Built here so the sibling qualifies even
    # though its own row carries no KPI flags.
    main_use_verif = {}
    for tree in trees:
        for edge in tree.get('edges', []):
            re_edge = resolve_edge_variant(edge, edge_overrides)
            asets = re_edge.get('action_sets') or []
            if asets and asets[0].get('actions') and asets[0].get('id'):
                main_use_verif[(re_edge.get('source_node_id'), asets[0]['id'])] = (
                    asets[0].get('use_verifications_for_kpi') is True
                )

    # Dedup key is (action_set_id, dest_id), NOT action_set_id alone: conditional
    # siblings SHARE the owner's action_set_id but reach distinct destinations, so
    # keying on id alone collapsed every sibling into one row. (dest_id, not the
    # edge, so the same shared id reached via two edges to the same node still
    # dedups.)
    seen = set()
    out = []
    for tree in trees:
        for edge in tree.get('edges', []):
            resolved_edge = resolve_edge_variant(edge, edge_overrides)
            if not resolved_edge.get('__variant_state', {}).get('active', True):
                continue
            source_id = resolved_edge.get('source_node_id')
            target_id = resolved_edge.get('target_node_id')
            # Either endpoint disabled by variant → drop the edge (matches the
            # runtime auto-skip in create_unified_networkx_graph).
            if source_id not in node_lookup or target_id not in node_lookup:
                continue
            action_sets = resolved_edge.get('action_sets') or []
            for i, action_set in enumerate(action_sets):
                aset_id = action_set.get('id')
                if not aset_id:
                    continue
                # Forward (i=0): measure target node. Reverse (i=1): measure
                # the original source (we're going the other way).
                dest_id = target_id if i == 0 else source_id
                orig_id = source_id if i == 0 else target_id
                if (aset_id, dest_id) in seen:
                    continue
                dest_info = node_lookup.get(dest_id)
                if not dest_info:
                    continue

                has_kpi_refs = bool(action_set.get('kpi_references'))
                uses_target = action_set.get('use_verifications_for_kpi') is True
                # Conditional sibling (forward, empty actions, shares owner's id):
                # inherit the owner's measurement intent so it surfaces too.
                if i == 0 and not action_set.get('actions'):
                    uses_target = uses_target or main_use_verif.get((source_id, aset_id), False)

                if has_kpi_refs:
                    reason = 'kpi_references'
                elif uses_target and dest_info['has_verifications']:
                    reason = 'target_verifications'
                else:
                    continue

                seen.add((aset_id, dest_id))
                out.append({
                    'label': action_set.get('label', ''),
                    # Optional friendly KPI name (Edge Edit dialog → action_set.kpi_name).
                    # Surfaced so the RunTests edge picker can show it instead of the
                    # raw edge label. Empty string when unset.
                    'kpi_name': action_set.get('kpi_name') or '',
                    'action_set_id': aset_id,
                    'edge_id': resolved_edge.get('edge_id') or resolved_edge.get('id'),
                    'tree_id': tree['tree_id'],
                    'from_label': node_lookup.get(orig_id, {}).get('label', ''),
                    'to_label': dest_info['label'],
                    'reason': reason,
                })

    out.sort(key=lambda x: x['label'])
    return {'action_sets': out, 'tree_ids': tree_ids}, None


# ----------------------------------------------------------------------------
# Navigation node label cache — backs the goto-script node picker. Mirrors the
# KPI action-set cache: keyed on (team, userinterface_name), MEDIUM_TTL,
# invalidated alongside the KPI entries on any tree/node/edge write via
# invalidate_cached_tree().
# ----------------------------------------------------------------------------

_navigation_nodes_cache = {}
_nav_nodes_cache_lock = threading.Lock()


def _invalidate_navigation_nodes_for_tree(tree_id: str):
    with _nav_nodes_cache_lock:
        to_drop = [k for k, v in _navigation_nodes_cache.items()
                   if tree_id in v.get('tree_ids', ())]
        for k in to_drop:
            del _navigation_nodes_cache[k]
        if to_drop:
            print(f"[@cache] INVALIDATE NAV_NODES: {len(to_drop)} entries for tree {tree_id}")


def _compute_navigation_nodes(userinterface_name: str, team_id: str, variant: Optional[str] = None):
    """Resolve userinterface → root tree → hierarchy, then return the
    deduplicated, sorted list of node labels across the full hierarchy.
    Drives the goto script's node dropdown on the RunTests modal.

    Variant scope (`variant=None` = base) is applied via `resolve_node_variant`.
    In variant scope a `hidden_in_base` row that the variant doesn't explicitly
    disable appears in the dropdown; in base scope it doesn't. Rows disabled by
    the variant entry drop out. Same semantics the runtime graph uses, so the
    dropdown never lies about what `goto` can reach.

    Returns ({'nodes': [...], 'tree_ids': [...]}, None) or (None, error).
    """
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import (
        get_complete_tree_hierarchy,
    )
    from shared.src.lib.utils.navigation_graph import resolve_node_variant

    ui = get_userinterface_by_name(userinterface_name, team_id)
    if not ui:
        return None, f"Userinterface '{userinterface_name}' not found"

    scope_bundle, err = _resolve_variant_overrides(ui['id'], team_id, variant)
    if err:
        return None, f"{err} for userinterface '{userinterface_name}'"

    root_tree = get_root_tree_for_interface(ui['id'], team_id)
    if not root_tree:
        return None, f"No root tree for userinterface '{userinterface_name}'"

    hierarchy = get_complete_tree_hierarchy(root_tree['id'], team_id)
    if not hierarchy.get('success'):
        return None, hierarchy.get('error', 'Failed to load tree hierarchy')

    trees = hierarchy.get('all_trees_data') or []
    tree_ids = [t['tree_id'] for t in trees]

    node_overrides, _edge_overrides = _compose_scope_overrides(scope_bundle, trees)

    seen = set()
    out = []
    for tree in trees:
        for node in tree.get('nodes', []):
            resolved = resolve_node_variant(node, node_overrides)
            if not resolved.get('__variant_state', {}).get('active', True):
                continue
            label = (resolved.get('label') or '').strip()
            if not label or label in seen:
                continue
            # ENTRY is a virtual start point; goto.py cannot target it
            # (see kpi_measurement.py:385). Hide from the dropdown.
            if label.upper() == 'ENTRY':
                continue
            seen.add(label)
            node_data = resolved.get('data') if isinstance(resolved.get('data'), dict) else {}
            out.append({
                'label': label,
                'node_id': resolved.get('node_id') or resolved.get('id'),
                'tree_id': tree['tree_id'],
                'node_type': resolved.get('node_type') or resolved.get('type') or '',
                # Optional friendly name (Node Edit dialog → data.display_name).
                # Lets the node picker show it instead of the raw label. Empty when unset.
                'display_name': node_data.get('display_name') or '',
            })

    out.sort(key=lambda x: x['label'])
    return {'nodes': out, 'tree_ids': tree_ids}, None


# ============================================================================
# TREE METADATA ENDPOINTS
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_all_navigation_trees')
def get_all_navigation_trees():
    """Get all navigation trees metadata for a team."""
    # Extract HTTP request data
    team_id = request.args.get('team_id')
    user_agent = request.headers.get('User-Agent', 'Unknown')
    referer = request.headers.get('Referer', 'Unknown')
    
    # Delegate to service layer (business logic moved out of route)
    from services.navigation_service import navigation_service
    result = navigation_service.get_all_navigation_trees(team_id, user_agent, referer)
    
    # Return HTTP response
    if result['success']:
        return jsonify({
            'success': True,
            'trees': result['trees']
        })
    else:
        status_code = result.get('status_code', 500)
        return jsonify({
            'success': False,
            'message': result['error']
        }), status_code
        
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_metadata_api')
def get_tree_metadata_api(tree_id):
    """Get tree metadata."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    
    result = get_tree_metadata(tree_id, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 404
@server_navigation_trees_bp.route('/navigationTrees', methods=['POST'])
@handle_route_exceptions('navigation_trees:create_tree_api')
def create_tree_api():
    """Create a new navigation tree."""
    tree_data = request.get_json()
    
    if not tree_data:
        return jsonify({
            'success': False,
            'message': 'No tree data provided'
        }), 400
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    
    result = save_tree_metadata(tree_data, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>', methods=['PUT'])
@handle_route_exceptions('navigation_trees:update_tree_api')
def update_tree_api(tree_id):
    """Update tree metadata."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    tree_data = request.get_json()
    
    if not tree_data:
        return jsonify({
            'success': False,
            'message': 'No tree data provided'
        }), 400
    
    tree_data['id'] = tree_id
    result = save_tree_metadata(tree_data, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>', methods=['DELETE'])
@handle_route_exceptions('navigation_trees:delete_tree_api')
def delete_tree_api(tree_id):
    """Delete a tree."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = delete_tree(tree_id, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
# ============================================================================
# NODE ENDPOINTS
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/nodes', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_nodes_api')
def get_tree_nodes_api(tree_id):
    """Get nodes for a tree with pagination."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    page = int(request.args.get('page', 0))
    limit = int(request.args.get('limit', 100))
    
    result = get_tree_nodes(tree_id, team_id, page, limit)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/nodes/<node_id>', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_node_api')
def get_node_api(tree_id, node_id):
    """Get a single node by its node_id."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    # Use robust node resolution - try node_id first, fallback to label
    result = resolve_node(tree_id, node_id, team_id, prefer_id=True)

    if result['success']:
        # Add resolution method info to response for debugging/transparency
        response_data = result.copy()
        response_data['resolution_method'] = result.get('resolution_method')
        return jsonify(response_data)
    else:
        return jsonify(result), 404
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/nodes', methods=['POST'])
@handle_route_exceptions('navigation_trees:create_node_api')
def create_node_api(tree_id):
    """
    Create a new node.
    
    Node Structure:
    {
        "node_id": "string",
        "label": "string", 
        "node_type": "screen|entry|...",
        "position_x": number,
        "position_y": number,
        "verifications": [...]  # ⚠️ TOP-LEVEL FIELD - verifications go HERE, not in data.verifications
        "data": {...}           # Metadata only - don't put verifications here
    }
    
    Note: The backend will auto-migrate verifications from data.verifications to root level
    as a safety measure, but always put them at the top level in your requests.
    """
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    node_data = request.get_json()
    
    if not node_data:
        return jsonify({
            'success': False,
            'message': 'No node data provided'
        }), 400
    
    result = save_node(tree_id, node_data, team_id)

    if result['success']:
        # Local tree-cache only — frontend follows up with `/server/cache/update-node`
        # which `add_node`s into the host graph (handles new nodes natively).
        # Wiping the host cache here would race that patch and leave it empty.
        invalidate_cached_tree(tree_id, team_id, propagate_to_hosts=False)

        # Invalidate user interfaces cache (first node creation makes tree visible)
        from backend_server.src.routes.server_userinterface_routes import _invalidate_interfaces_cache
        _invalidate_interfaces_cache(team_id)
        
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/nodes/<node_id>', methods=['PUT'])
@handle_route_exceptions('navigation_trees:update_node_api')
def update_node_api(tree_id, node_id):
    """
    Update a node.
    
    Updates Structure:
    {
        "verifications": [...]  # ⚠️ TOP-LEVEL FIELD - verifications go HERE, not in data.verifications
        "data": {...}           # Metadata only - don't put verifications here
        ... other fields ...
    }
    
    Note: The backend will auto-migrate verifications from data.verifications to root level
    as a safety measure, but always put them at the top level in your requests.
    """
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    node_data = request.get_json()

    if not node_data:
        return jsonify({
            'success': False,
            'message': 'No node data provided'
        }), 400

    # ✅ VALIDATION: variant_overrides was retired — variant data lives on the
    # variant row (userinterface_variants.node_overrides). Reject explicit sends
    # so a stale frontend doesn't silently no-op a save.
    if 'variant_overrides' in node_data:
        return jsonify({
            'success': False,
            'message': "'variant_overrides' is no longer accepted on nodes; per-variant overrides are written to PUT /server/userinterface/<id>/variants/<name>",
        }), 400

    # `hidden_in_base` is a top-level boolean column. Validate type if present.
    if 'hidden_in_base' in node_data and not isinstance(node_data.get('hidden_in_base'), bool):
        return jsonify({'success': False, 'message': "'hidden_in_base' must be a boolean"}), 400

    # ✅ VALIDATION: Check verifications if provided
    verifications = node_data.get('verifications', [])
    if verifications:
        # Get userinterface to determine device_model
        from shared.src.lib.database.navigation_trees_db import get_tree_metadata
        tree_metadata = get_tree_metadata(tree_id, team_id)
        
        if tree_metadata and tree_metadata.get('success'):
            userinterface_id = tree_metadata.get('tree', {}).get('userinterface_id')
            
            if userinterface_id:
                from shared.src.lib.database.userinterface_db import get_userinterface
                ui_result = get_userinterface(userinterface_id, team_id)
                
                if ui_result and ui_result.get('success'):
                    device_model = ui_result.get('userinterface', {}).get('device_model', 'unknown')
                    
                    # Import validator
                    from backend_server.src.mcp.utils.api_client import MCPAPIClient
                    from backend_server.src.mcp.utils.verification_validator import VerificationValidator
                    from shared.src.lib.config.constants import APP_CONFIG
                    
                    api_client = MCPAPIClient(
                        APP_CONFIG.get('BACKEND_SERVER_URL', 'http://localhost:5000')
                    )
                    validator = VerificationValidator(api_client)
                    
                    is_valid, errors, warnings = validator.validate_verifications(
                        verifications,
                        device_model
                    )
                    
                    if not is_valid:
                        error_msg = "❌ Invalid verification command(s):\n\n"
                        error_msg += "\n".join(errors)
                        error_msg += "\n\n" + validator.get_valid_commands_for_display(device_model)
                        
                        return jsonify({
                            'success': False,
                            'message': error_msg,
                            'errors': errors
                        }), 400
                    
                    # Log warnings but allow save
                    if warnings:
                        print(f"[@route:navigation_trees:update_node] ⚠️ Verification warnings:")
                        for warning in warnings:
                            print(f"  {warning}")
    
    node_data['node_id'] = node_id
    result = save_node(tree_id, node_data, team_id)

    if result['success']:
        # Invalidate ONLY the local tree-response cache. The frontend follows
        # up with `/server/cache/update-node` to patch the host's unified
        # graph in place; clearing the host cache here would race that patch
        # and leave the graph empty (cache miss → 0/0 on next edge run).
        invalidate_cached_tree(tree_id, team_id, propagate_to_hosts=False)

        # No need to invalidate interfaces cache for node updates (doesn't affect visibility)
        
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/nodes/<node_id>', methods=['DELETE'])
@handle_route_exceptions('navigation_trees:delete_node_api')
def delete_node_api(tree_id, node_id):
    """Delete a node."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = delete_node(tree_id, node_id, team_id)
    
    if result['success']:
        # Invalidate tree cache when node is deleted
        invalidate_cached_tree(tree_id, team_id)
        
        # Invalidate user interfaces cache (deleting all nodes makes tree invisible)
        from backend_server.src.routes.server_userinterface_routes import _invalidate_interfaces_cache
        _invalidate_interfaces_cache(team_id)
        
        return jsonify(result)
    else:
        return jsonify(result), 400
# ============================================================================
# EDGE ENDPOINTS
# ============================================================================

def _variant_cache_key(variant: Optional[str]) -> str:
    """Cache-key suffix matching navigation_cache._variant_key — '__base__'
    is the reserved sentinel for the base scope."""
    return (variant or '').strip().lower() or '__base__'


@server_navigation_trees_bp.route('/navigationTrees/kpi-action-sets', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_kpi_action_sets')
def get_kpi_action_sets_api():
    """List action_sets across a userinterface's full tree hierarchy that have
    KPI measurement enabled. Drives the kpi_measurement script's edge picker
    on the RunTests modal.

    Variant scope is taken from the optional `variant` query param (omit /
    empty = base). The returned set matches what `goto`-style navigation
    would actually see at runtime under that variant — rows disabled by the
    variant entry or `hidden_in_base` (base scope) drop out, and action_sets
    come from the variant-resolved edge so overrides that replace
    `action_sets` are honoured.

    Cached per (team_id, userinterface_name, variant) at MEDIUM_TTL;
    auto-invalidated via invalidate_cached_tree() on tree/node/edge writes
    and via the variant write routes (PUT/DELETE/rename) for variant edits.
    """
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    team_id = request.args.get('team_id')
    userinterface_name = request.args.get('userinterface_name')
    # Canonicalize (sorted, '+'-joined) so a composition selection hits the
    # same cache entry regardless of the order the user picked variants in.
    variant = canonical_variant_name(request.args.get('variant'))
    if not team_id or not userinterface_name:
        return jsonify({
            'success': False,
            'message': 'team_id and userinterface_name are required'
        }), 400

    variant_key = _variant_cache_key(variant)
    cache_key = (team_id, userinterface_name, variant_key)
    with _kpi_cache_lock:
        cached = _kpi_action_sets_cache.get(cache_key)
        if cached and (time.time() - cached['timestamp']) < CACHE_CONFIG['MEDIUM_TTL']:
            print(f"[@cache] HIT KPI: {userinterface_name}@{variant_key} ({len(cached['data'])} sets)")
            return jsonify({'success': True, 'action_sets': cached['data'], 'cached': True})
        if cached:
            del _kpi_action_sets_cache[cache_key]

    result, error = _compute_kpi_action_sets(userinterface_name, team_id, variant)
    if error:
        return jsonify({'success': False, 'message': error}), 404

    with _kpi_cache_lock:
        _kpi_action_sets_cache[cache_key] = {
            'data': result['action_sets'],
            'timestamp': time.time(),
            'tree_ids': set(result['tree_ids']),
        }
    print(f"[@cache] SET KPI: {userinterface_name}@{variant_key} ({len(result['action_sets'])} sets)")
    return jsonify({'success': True, 'action_sets': result['action_sets'], 'cached': False})


@server_navigation_trees_bp.route('/navigationTrees/nodes', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_navigation_nodes')
def get_navigation_nodes_api():
    """List node labels across a userinterface's full tree hierarchy. Drives
    the goto script's node picker on the RunTests modal (analogue of the
    kpi-action-sets endpoint).

    Variant scope is taken from the optional `variant` query param (omit /
    empty = base). The list matches what `goto` can actually reach at runtime
    under that variant: variant-disabled rows drop out; in base scope rows
    flagged `hidden_in_base` are also hidden.

    Cached per (team_id, userinterface_name, variant) at MEDIUM_TTL;
    auto-invalidated alongside the KPI cache on tree/node/edge/variant writes.
    """
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    team_id = request.args.get('team_id')
    userinterface_name = request.args.get('userinterface_name')
    # Canonicalize (sorted, '+'-joined) — same reasoning as kpi-action-sets.
    variant = canonical_variant_name(request.args.get('variant'))
    if not team_id or not userinterface_name:
        return jsonify({
            'success': False,
            'message': 'team_id and userinterface_name are required'
        }), 400

    variant_key = _variant_cache_key(variant)
    cache_key = (team_id, userinterface_name, variant_key)
    with _nav_nodes_cache_lock:
        cached = _navigation_nodes_cache.get(cache_key)
        if cached and (time.time() - cached['timestamp']) < CACHE_CONFIG['MEDIUM_TTL']:
            print(f"[@cache] HIT NAV_NODES: {userinterface_name}@{variant_key} ({len(cached['data'])} nodes)")
            return jsonify({'success': True, 'nodes': cached['data'], 'cached': True})
        if cached:
            del _navigation_nodes_cache[cache_key]

    result, error = _compute_navigation_nodes(userinterface_name, team_id, variant)
    if error:
        return jsonify({'success': False, 'message': error}), 404

    with _nav_nodes_cache_lock:
        _navigation_nodes_cache[cache_key] = {
            'data': result['nodes'],
            'timestamp': time.time(),
            'tree_ids': set(result['tree_ids']),
        }
    print(f"[@cache] SET NAV_NODES: {userinterface_name}@{variant_key} ({len(result['nodes'])} nodes)")
    return jsonify({'success': True, 'nodes': result['nodes'], 'cached': False})


def invalidate_picker_caches_for_variant(team_id: str, userinterface_name: str, variant_name: Optional[str]):
    """Drop kpi-action-sets + navigation-nodes cache entries scoped to a
    single (team, userinterface, variant). Called from the variant write
    routes (PUT/DELETE/rename) in server_userinterface_routes after any
    change to `userinterface_variants` that could affect what the pickers
    list. The tree-based invalidation hook
    (_invalidate_kpi_action_sets_for_tree / _invalidate_navigation_nodes_for_tree)
    only fires on node/edge writes, which is why this variant-write hook is
    its own thing.

    `variant_name=None` drops the base entry, which is what callers want
    after a rename so both the old and new variant entries are evicted (the
    new one doesn't exist yet, but the old needs to go).
    """
    variant_key = _variant_cache_key(variant_name)

    def _matches(key) -> bool:
        # Exact key, PLUS any composite entry ('a+b') that contains the edited
        # variant as a component — a composition's picker lists change when any
        # of its members change.
        if key[0] != team_id or key[1] != userinterface_name:
            return False
        if key[2] == variant_key:
            return True
        return variant_key != '__base__' and variant_key in key[2].split('+')

    with _kpi_cache_lock:
        for key in [k for k in _kpi_action_sets_cache if _matches(k)]:
            del _kpi_action_sets_cache[key]
            print(f"[@cache] INVALIDATE KPI: {userinterface_name}@{key[2]} (variant write)")
    with _nav_nodes_cache_lock:
        for key in [k for k in _navigation_nodes_cache if _matches(k)]:
            del _navigation_nodes_cache[key]
            print(f"[@cache] INVALIDATE NAV_NODES: {userinterface_name}@{key[2]} (variant write)")


@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_edges_api')
def get_tree_edges_api(tree_id):
    """Get edges, optionally filtered by nodes."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    node_ids = request.args.getlist('node_ids')
    
    result = get_tree_edges(tree_id, team_id, node_ids if node_ids else None)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges/<edge_id>', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_edge_api')
def get_edge_api(tree_id, edge_id):
    """Get a single edge by its edge_id."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = get_edge_by_id(tree_id, edge_id, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 404
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges/validate', methods=['POST'])
@handle_route_exceptions('navigation_trees:validate_edge_actions_api')
def validate_edge_actions_api(tree_id):
    """On-demand validation of edge action commands (decoupled from save)."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'message': 'team_id is required'}), 400

    edge_data = request.get_json() or {}
    action_sets = edge_data.get('action_sets', [])
    if not action_sets:
        return jsonify({'success': True, 'errors': [], 'warnings': []})

    tree_metadata = get_tree_metadata(tree_id, team_id)
    if not (tree_metadata and tree_metadata.get('success')):
        return jsonify({'success': True, 'errors': [], 'warnings': []})

    userinterface_id = tree_metadata.get('tree', {}).get('userinterface_id')
    if not userinterface_id:
        return jsonify({'success': True, 'errors': [], 'warnings': []})

    from shared.src.lib.database.userinterface_db import get_userinterface
    ui_result = get_userinterface(userinterface_id, team_id)
    if not (ui_result and ui_result.get('success')):
        return jsonify({'success': True, 'errors': [], 'warnings': []})

    device_model = ui_result.get('userinterface', {}).get('device_model', 'unknown')

    from backend_server.src.lib.utils.action_validator import ActionValidator
    validator = ActionValidator()
    is_valid, errors, warnings = validator.validate_action_sets(
        action_sets,
        device_model,
        host_name=edge_data.get('host_name'),
        device_id=edge_data.get('device_id'),
    )

    payload = {'success': is_valid, 'errors': errors, 'warnings': warnings}
    if not is_valid:
        payload['message'] = "❌ Invalid action command(s):\n\n" + "\n".join(errors)
    return jsonify(payload)


@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges', methods=['POST'])
@handle_route_exceptions('navigation_trees:create_edge_api')
def create_edge_api(tree_id):
    """Create a new edge."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    edge_data = request.get_json()
    
    if not edge_data:
        return jsonify({
            'success': False,
            'message': 'No edge data provided'
        }), 400
    
    # Action-command validation is now async (see /navigationTrees/<tree_id>/edges/validate).
    # The host re-validates at execution time, so the save path stays fast.
    result = save_edge(tree_id, edge_data, team_id)

    if result['success']:
        # Local tree-cache only — frontend follows up with `/server/cache/update-edge`.
        # `update_edge_in_cache` requires both endpoint nodes to already be in the
        # host graph; wiping here would force a cache rebuild via take-control.
        invalidate_cached_tree(tree_id, team_id, propagate_to_hosts=False)
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges/<edge_id>', methods=['PUT'])
@handle_route_exceptions('navigation_trees:update_edge_api')
def update_edge_api(tree_id, edge_id):
    """Update an edge."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    edge_data = request.get_json()

    if not edge_data:
        return jsonify({
            'success': False,
            'message': 'No edge data provided'
        }), 400

    # variant_overrides was retired — variant data lives on the variant row.
    if 'variant_overrides' in edge_data:
        return jsonify({
            'success': False,
            'message': "'variant_overrides' is no longer accepted on edges; per-variant overrides are written to PUT /server/userinterface/<id>/variants/<name>",
        }), 400

    if 'hidden_in_base' in edge_data and not isinstance(edge_data.get('hidden_in_base'), bool):
        return jsonify({'success': False, 'message': "'hidden_in_base' must be a boolean"}), 400

    # Action-command validation is now async (see /navigationTrees/<tree_id>/edges/validate).
    # The host re-validates at execution time, so the save path stays fast.
    edge_data['edge_id'] = edge_id
    result = save_edge(tree_id, edge_data, team_id)

    if result['success']:
        # Invalidate ONLY the local tree-response cache. The frontend follows
        # up with `/server/cache/update-edge` to patch the host graph in place;
        # clearing the host cache here would race that patch and leave the
        # graph empty (cache miss → 0/0 on next edge run).
        invalidate_cached_tree(tree_id, team_id, propagate_to_hosts=False)
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/edges/<edge_id>', methods=['DELETE'])
@handle_route_exceptions('navigation_trees:delete_edge_api')
def delete_edge_api(tree_id, edge_id):
    """Delete an edge."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = delete_edge(tree_id, edge_id, team_id)
    
    if result['success']:
        # Invalidate cache when edge is deleted
        invalidate_cached_tree(tree_id, team_id)
        return jsonify(result)
    else:
        return jsonify(result), 400
# ============================================================================
# NESTED TREE ENDPOINTS
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees/getNodeSubTrees/<tree_id>/<node_id>', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_node_sub_trees_api')
def get_node_sub_trees_api(tree_id, node_id):
    """Get all sub-trees for a specific node."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = get_node_sub_trees(tree_id, node_id, team_id)
    return jsonify(result)
@server_navigation_trees_bp.route('/navigationTrees/<parent_tree_id>/nodes/<parent_node_id>/subtrees', methods=['POST'])
@handle_route_exceptions('navigation_trees:create_sub_tree_api')
def create_sub_tree_api(parent_tree_id, parent_node_id):
    """Create a new sub-tree for a specific node."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    tree_data = request.get_json()
    
    if not tree_data:
        return jsonify({
            'success': False,
            'message': 'No tree data provided'
        }), 400
    
    result = create_sub_tree(parent_tree_id, parent_node_id, tree_data, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/hierarchy', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_hierarchy_api')
def get_tree_hierarchy_api(tree_id):
    """Get complete tree hierarchy starting from root."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = get_tree_hierarchy(tree_id, team_id)
    return jsonify(result)
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/breadcrumb', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_breadcrumb_api')
def get_tree_breadcrumb_api(tree_id):
    """Get breadcrumb path for a tree."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = get_tree_breadcrumb(tree_id, team_id)
    return jsonify(result)
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/cascade', methods=['DELETE'])
@handle_route_exceptions('navigation_trees:delete_tree_cascade_api')
def delete_tree_cascade_api(tree_id):
    """Delete a tree and all its descendant trees."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = delete_tree_cascade(tree_id, team_id)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<subtree_id>/move', methods=['PUT'])
@handle_route_exceptions('navigation_trees:move_subtree_api')
def move_subtree_api(subtree_id):
    """Move a subtree to a different parent node."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    data = request.get_json()
    
    if not data or 'new_parent_tree_id' not in data or 'new_parent_node_id' not in data:
        return jsonify({
            'success': False,
            'message': 'Missing required fields: new_parent_tree_id, new_parent_node_id'
        }), 400
    
    result = move_subtree(
        subtree_id, 
        data['new_parent_tree_id'], 
        data['new_parent_node_id'], 
        team_id
    )
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 400
# ============================================================================
# BATCH OPERATIONS
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/full', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_full_tree_api')
def get_full_tree_api(tree_id):
    """Get complete tree data (metadata + nodes + edges)."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    result = get_full_tree(tree_id, team_id)
    
    if result['success']:
        # Cache population moved to "Take Control" flow - no longer done during tree loading
        
        return jsonify(result)
    else:
        return jsonify(result), 404
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/batch', methods=['POST'])
@handle_route_exceptions('navigation_trees:save_tree_data_api')
def save_tree_data_api(tree_id):
    """Save complete tree data (nodes + edges) in batch."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    data = request.get_json()
    
    if not data:
        return jsonify({
            'success': False,
            'message': 'No data provided'
        }), 400
    
    nodes = data.get('nodes', [])
    edges = data.get('edges', [])
    deleted_node_ids = data.get('deleted_node_ids', [])
    deleted_edge_ids = data.get('deleted_edge_ids', [])
    
    viewport = data.get('viewport')
    result = save_tree_data(tree_id, nodes, edges, team_id, deleted_node_ids, deleted_edge_ids, viewport)
    
    if result['success']:
        # Invalidate tree cache when tree is modified
        invalidate_cached_tree(tree_id, team_id)
        
        # Invalidate user interfaces cache so getAllUserInterfaces refreshes root_tree status
        from backend_server.src.routes.server_userinterface_routes import _invalidate_interfaces_cache
        _invalidate_interfaces_cache(team_id)
        print(f"[@route:navigation_trees:save_batch] Invalidated interfaces cache for team {team_id}")
        
        return jsonify(result)
    else:
        return jsonify(result), 400
# ============================================================================
# INTERFACE OPERATIONS
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees/getTreeByUserInterfaceId/<userinterface_id>', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_by_userinterface_id')
def get_tree_by_userinterface_id(userinterface_id):
    """
    Get navigation tree for a specific user interface (with 5-min cache).
    
    Query parameters:
        include_metrics: boolean (default: false) - Include metrics data with tree data
                        Set to true to get tree + metrics in a single call (reduces 2 calls to 1)
        include_nested: boolean (default: false) - Include all nested subtrees
                        Set to true to get complete hierarchy (root + all nested trees)
    """
    team_id = request.args.get('team_id') 
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400
    
    # Check if we should include metrics (defaults to false for backward compatibility)
    include_metrics = request.args.get('include_metrics', 'false').lower() == 'true'

    # Check if we should include nested trees (defaults to false for backward compatibility)
    include_nested = request.args.get('include_nested', 'false').lower() == 'true'

    # Run scope filter for metrics: lowercase variant name or None for base.
    # The cache key for the tree itself does NOT include variant (the topology
    # is the same in every scope); metrics are fetched fresh per variant.
    raw_variant = request.args.get('variant')
    variant = (raw_variant or '').strip().lower() or None if isinstance(raw_variant, str) else None
    
    # Get the root tree for this user interface
    tree = get_root_tree_for_interface(userinterface_id, team_id)
    
    if tree:
        tree_id = tree['id']
        
        # If nested trees requested, load complete hierarchy (no cache for now)
        if include_nested:
            print(f"[@route:navigation_trees] Loading complete hierarchy for tree {tree_id}")
            from shared.src.lib.database.navigation_trees_db import get_complete_tree_hierarchy
            
            hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
            
            if hierarchy_result.get('success'):
                all_trees_data = hierarchy_result.get('all_trees_data', [])
                
                # Flatten all nodes from all trees, but exclude duplicate nodes from nested trees
                # Duplicates occur when a parent node (with has_subtree=true) also exists as entry in the subtree
                all_nodes = []
                all_edges = []
                
                # Track seen node IDs and labels to avoid duplicates
                seen_node_ids = set()
                seen_labels = set()
                
                for tree_data in all_trees_data:
                    tree_info = tree_data.get('tree_info', {})
                    is_root_tree = tree_info.get('is_root_tree', False)
                    
                    nodes = tree_data.get('nodes', [])
                    edges = tree_data.get('edges', [])
                    
                    if is_root_tree:
                        # For root tree, include all nodes and track them
                        for node in nodes:
                            all_nodes.append(node)
                            seen_node_ids.add(node.get('node_id'))
                            seen_labels.add(node.get('label'))
                        print(f"[@route:navigation_trees] Root tree: added {len(nodes)} nodes")
                    else:
                        # For nested trees, skip nodes that already exist in parent
                        unique_nodes = []
                        skipped_count = 0
                        for node in nodes:
                            node_id = node.get('node_id')
                            label = node.get('label')
                            
                            # Skip if we've already seen this node_id or label
                            if node_id in seen_node_ids or label in seen_labels:
                                print(f"[@route:navigation_trees] Skipping duplicate node: {label} (already in parent tree)")
                                skipped_count += 1
                                continue
                            
                            unique_nodes.append(node)
                            seen_node_ids.add(node_id)
                            seen_labels.add(label)
                        
                        all_nodes.extend(unique_nodes)
                        print(f"[@route:navigation_trees] Nested tree '{tree_info.get('name', 'unknown')}': added {len(unique_nodes)} nodes (skipped {skipped_count} duplicates)")
                    
                    # Include all edges from all trees
                    all_edges.extend(edges)
                
                response_data = {
                    'success': True,
                    'tree': {
                        'id': tree['id'],
                        'name': tree['name'],
                        'viewport_x': tree.get('viewport_x', 0),
                        'viewport_y': tree.get('viewport_y', 0),
                        'viewport_zoom': tree.get('viewport_zoom', 1),
                        'metadata': {
                            'nodes': all_nodes,
                            'edges': all_edges
                        }
                    },
                    'nested_trees_count': len(all_trees_data),
                    # Unflattened per-tree hierarchy (root + every nested tree,
                    # each with its own nodes/edges and parent linkage). Lets the
                    # client list every node across the whole interface and
                    # reconstruct the breadcrumb chain to any subtree node.
                    'all_trees_data': all_trees_data
                }
                
                print(f"[@route:navigation_trees] Loaded {len(all_trees_data)} trees with {len(all_nodes)} total unique nodes")
                return jsonify(response_data)
            else:
                return jsonify({
                    'success': False,
                    'error': f'Failed to load tree hierarchy: {hierarchy_result.get("error", "Unknown error")}'
                })
        
        # Try cache first (avoids 3 DB queries!) - only for non-nested requests.
        # NOTE: cache holds tree topology only (no metrics), so the same cache
        # entry serves every variant. Metrics are fetched fresh per variant
        # from the pre-aggregated tables (~5ms RPC).
        cached_result = get_cached_tree(tree_id, team_id)
        if cached_result:
            if include_metrics:
                print(f"[@cache] HIT: Tree {tree_id}, fetching metrics (variant={variant or 'base'})...")
                metrics_data = _fetch_tree_metrics(tree_id, team_id, variant)
                # Build a response copy so the cached entry never mutates per-variant.
                response_copy = dict(cached_result)
                if metrics_data:
                    response_copy['metrics'] = metrics_data
                else:
                    response_copy.pop('metrics', None)
                return jsonify(response_copy)
            return jsonify(cached_result)

        # Cache miss - fetch from database
        print(f"[@cache] MISS: Tree {tree_id} - fetching from DB")
        result = get_full_tree(tree_id, team_id)

        if result['success']:
            # Build response (without metrics — those are variant-scoped)
            response_data = {
                'success': True,
                'tree': {
                    'id': tree['id'],
                    'name': tree['name'],
                    'viewport_x': tree.get('viewport_x', 0),
                    'viewport_y': tree.get('viewport_y', 0),
                    'viewport_zoom': tree.get('viewport_zoom', 1),
                    'metadata': {
                        'nodes': result.get('nodes', []),
                        'edges': result.get('edges', [])
                    }
                }
            }

            # Cache the bare tree (no metrics — those depend on variant).
            set_cached_tree(tree_id, team_id, response_data)

            # Fetch metrics if requested (combines 2 API calls into 1)
            if include_metrics:
                print(f"[@cache] Including metrics for tree {tree_id} (variant={variant or 'base'})")
                metrics_data = _fetch_tree_metrics(tree_id, team_id, variant)
                if metrics_data:
                    response_data = dict(response_data)
                    response_data['metrics'] = metrics_data
            
            # Prevent browser caching - always fetch fresh from server
            response = jsonify(response_data)
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            return response
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to load tree data: {result.get("error", "Unknown error")}'
            })
    else:
        return jsonify({
            'success': False,
            'error': f'No navigation tree found for user interface: {userinterface_id}'
        })
@server_navigation_trees_bp.route('/navigationTrees/lockStatus', methods=['GET'])
@handle_route_exceptions('navigation_trees:check_lock_status')
def check_lock_status():
    """Check lock status for a navigation tree (placeholder for future locking)."""
    userinterface_id = request.args.get('userinterface_id')
    
    if not userinterface_id:
        return jsonify({
            'success': False,
            'message': 'Missing required parameter: userinterface_id'
        }), 400
    
    # For now, always return not locked (implement actual locking later)
    return jsonify({
        'success': True,
        'lock': None
    })
@server_navigation_trees_bp.route('/navigationTrees/lockAcquire', methods=['POST'])
@handle_route_exceptions('navigation_trees:acquire_lock')
def acquire_lock():
    """Acquire lock for a navigation tree (placeholder for future locking)."""
    data = request.get_json()
    
    if not data:
        return jsonify({
            'success': False,
            'message': 'Missing request body'
        }), 400
        
    userinterface_id = data.get('userinterface_id')
    session_id = data.get('session_id')
    user_id = data.get('user_id')
    
    if not all([userinterface_id, session_id, user_id]):
        return jsonify({
            'success': False,
            'message': 'Missing required parameters: userinterface_id, session_id, user_id'
        }), 400
    
    # For now, always return successful lock acquisition
    return jsonify({
        'success': True,
        'lock': {
            'userinterface_id': userinterface_id,
            'session_id': session_id,
            'user_id': user_id,
            'locked_at': '2025-01-29T12:00:00Z'
        }
    })
@server_navigation_trees_bp.route('/navigationTrees/lockRelease', methods=['POST'])
@handle_route_exceptions('navigation_trees:release_lock')
def release_lock():
    """Release lock for a navigation tree (placeholder for future locking)."""
    data = request.get_json()
    
    if not data:
        return jsonify({
            'success': False,
            'message': 'Missing request body'
        }), 400
        
    userinterface_id = data.get('userinterface_id')
    session_id = data.get('session_id')
    
    if not all([userinterface_id, session_id]):
        return jsonify({
            'success': False,
            'message': 'Missing required parameters: userinterface_id, session_id'
        }), 400
    
    # For now, always return successful lock release
    return jsonify({
        'success': True,
        'message': 'Lock released successfully'
    })
# ============================================================================
# TREE HISTORY & VERSIONING API
# ============================================================================

@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/history', methods=['GET'])
@handle_route_exceptions('navigation_trees:get_tree_history_api')
def get_tree_history_api(tree_id):
    """Get the last 10 versions of a tree from history."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400

    result = get_tree_history(tree_id, team_id, limit=10)

    if result['success']:
        # The frontend only renders three count fields from tree_data
        # (total_trees / total_nodes / total_edges). The rest of the JSONB blob
        # is the full nodes/edges snapshot used by the /restore endpoint and is
        # tens to hundreds of KB per row — strip it before serialising.
        versions = []
        for v in result.get('versions', []):
            tree_data = v.get('tree_data') or {}
            versions.append({
                **v,
                'tree_data': {
                    'total_trees': tree_data.get('total_trees'),
                    'total_nodes': tree_data.get('total_nodes'),
                    'total_edges': tree_data.get('total_edges'),
                },
            })
        return jsonify({
            'success': True,
            'versions': versions
        })
    else:
        return jsonify(result), 400
@server_navigation_trees_bp.route('/navigationTrees/<tree_id>/restore/<int:version_number>', methods=['POST'])
@handle_route_exceptions('navigation_trees:restore_tree_from_history_api')
def restore_tree_from_history_api(tree_id, version_number):
    """Restore a tree to a specific version from history."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'message': 'team_id is required'
        }), 400

    # Get user ID from request data if available
    data = request.get_json() or {}
    restored_by = data.get('restored_by')

    result = restore_tree_from_history(tree_id, version_number, team_id, restored_by)

    if result['success']:
        # Invalidate caches after restoration
        invalidate_cached_tree(tree_id, team_id)
        from backend_server.src.routes.server_userinterface_routes import _invalidate_interfaces_cache
        _invalidate_interfaces_cache(team_id)

        return jsonify(result)
    else:
        return jsonify(result), 400


@server_navigation_trees_bp.route('/userinterface/domReport', methods=['GET'])
@handle_route_exceptions('navigation_trees:dom_report')
def dom_report():
    """Serve the cached HTML DOM report for a userinterface, built from stored
    node.data.dom (no LLM). Opened in a new tab from the Interface page."""
    ui_name = request.args.get('userinterface')
    team_id = request.args.get('team_id')
    if not ui_name or not team_id:
        return jsonify({'success': False, 'message': 'userinterface and team_id are required'}), 400
    from backend_server.src.services.dom_report import build_dom_report
    html_doc = build_dom_report(ui_name, team_id)
    return html_doc, 200, {'Content-Type': 'text/html; charset=utf-8'}