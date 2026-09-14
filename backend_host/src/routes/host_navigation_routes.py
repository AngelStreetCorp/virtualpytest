"""
Host Navigation Routes - Device Navigation Execution

This module receives navigation execution requests from the server and routes them
to the appropriate device's NavigationExecutor.
"""

import time
import threading
from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event

# Create blueprint
host_navigation_bp = Blueprint('host_navigation', __name__, url_prefix='/host/navigation')

@host_navigation_bp.route('/execute/<tree_id>', methods=['POST'])
@route_exception_handler()
def navigation_execute(tree_id):
    """Start navigation execution — ALWAYS ASYNC.

    Returns immediately with {success: true, execution_id: ...}.
    The actual navigation runs in a background thread. Callers MUST poll
    /host/navigation/execution/<execution_id>/status (or listen for a
    socket event) to know when navigation has finished.

    The frontend does this via waitForExecutionSocketEvent() in
    navigationExecutionUtils.ts. Backend callers (e.g. _deterministic_prenav
    in server_testprompt_routes.py) must poll the status endpoint.
    """
    print(f"\n{'='*80}")
    print(f"[@route:host_navigation:navigation_execute] 🚀 NAVIGATION EXECUTION STARTED")
    print(f"{'='*80}")
    
    # Get request data
    data = request.get_json() or {}
    
    # Get explicit target parameters
    target_node_id = data.get('target_node_id')
    target_node_label = data.get('target_node_label')
    
    # Validate: Must provide exactly one
    if not target_node_id and not target_node_label:
        return jsonify({
            'success': False,
            'error': 'Either target_node_id or target_node_label is required in request body'
        }), 400
    
    if target_node_id and target_node_label:
        return jsonify({
            'success': False,
            'error': 'Cannot provide both target_node_id and target_node_label'
        }), 400
    
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    frontend_sent_position = 'current_node_id' in data
    current_node_id = data.get('current_node_id') if frontend_sent_position else None
    image_source_url = data.get('image_source_url')
    userinterface_name = data.get('userinterface_name')
    async_execution = data.get('async_execution', True)

    # Run scope: variant name(s) registered in userinterface_variants, or None
    # for base. May be a single name OR a composition (list / '+'/','-joined);
    # canonicalized to one sorted '+'-joined scope so cache + metrics attribution
    # match regardless of order. See docs/agent/navigation/VARIANT.md "Composition".
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    variant = canonical_variant_name(data.get('variant'))

    # Interactive Editor Goto runs flag is_test=true so per-step recording
    # excludes them from edge_metrics / node_metrics. Default false for CLI.
    is_test = bool(data.get('is_test', False))

    # Verification mode: 'end' (default) | 'each' | 'auto'. Forwarded to
    # NavigationExecutor.execute_navigation; controls which steps run
    # verify_node on their destination. KPI queueing is unaffected.
    verification_mode = (data.get('verification_mode') or 'end').strip().lower()
    if verification_mode not in ('end', 'each', 'auto'):
        verification_mode = 'end'
    
    print(f"[@route:host_navigation:navigation_execute]   → Target Node ID: {target_node_id}")
    print(f"[@route:host_navigation:navigation_execute]   → Target Node Label: {target_node_label}")
    print(f"[@route:host_navigation:navigation_execute]   → Tree ID: {tree_id}")
    print(f"[@route:host_navigation:navigation_execute]   → Device ID: {device_id}")
    print(f"[@route:host_navigation:navigation_execute]   → Team ID: {team_id}")
    print(f"[@route:host_navigation:navigation_execute]   → UserInterface: {userinterface_name}")
    print(f"[@route:host_navigation:navigation_execute]   → Current Node ID: {current_node_id if frontend_sent_position else 'Not provided'}")
    print(f"[@route:host_navigation:navigation_execute]   → Frontend Sent Position: {frontend_sent_position}")
    print(f"[@route:host_navigation:navigation_execute]   → Async Execution: {async_execution}")
    print(f"{'='*80}\n")
    
    # Validate
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
        
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    if not userinterface_name:
        return jsonify({'success': False, 'error': 'userinterface_name is required for reference resolution'}), 400
    
    # Get host device registry from app context
    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({
            'success': False, 
            'error': f'Device {device_id} not found in host'
        }), 404
    
    device = host_devices[device_id]

    # Stamp the run scope on the device's navigation_context so that
    # record_edge_execution / record_node_execution downstream pick it up
    # and the resolver applies the correct variant overrides.
    if not hasattr(device, 'navigation_context') or device.navigation_context is None:
        device.navigation_context = {}
    device.navigation_context['variant'] = variant
    device.navigation_context['is_test'] = is_test

    # Check if device has navigation_executor
    if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have NavigationExecutor initialized'
        }), 500

    # Always execute asynchronously to prevent HTTP timeouts
    # Generate execution ID
    import uuid
    execution_id = str(uuid.uuid4())
    
    # Store execution state
    if not hasattr(device.navigation_executor, '_executions'):
        device.navigation_executor._executions = {}
        device.navigation_executor._lock = threading.Lock()
    
    with device.navigation_executor._lock:
        device.navigation_executor._executions[execution_id] = {
            'execution_id': execution_id,
            'status': 'running',
            'tree_id': tree_id,
            'target_node_id': target_node_id,
            'target_node_label': target_node_label,
            'result': None,
            'error': None,
            'start_time': time.time(),
            'progress': 0,
            'message': 'Navigation starting...'
        }
    
    # Start execution in background thread using NavigationExecutor's own async management
    from backend_host.src.orchestrator import ExecutionOrchestrator
    
    def run_navigation():
        try:
            import asyncio
            result = asyncio.run(ExecutionOrchestrator.execute_navigation(
                device=device,
                tree_id=tree_id,
                userinterface_name=userinterface_name,
                target_node_id=target_node_id,
                target_node_label=target_node_label,
                current_node_id=current_node_id,
                frontend_sent_position=frontend_sent_position,
                image_source_url=image_source_url,
                team_id=team_id,
                context=None,
                verification_mode=verification_mode,
            ))

            # Update execution state with result
            with device.navigation_executor._lock:
                # Check if navigation actually succeeded
                if result.get('success'):
                    device.navigation_executor._executions[execution_id]['status'] = 'completed'
                    device.navigation_executor._executions[execution_id]['result'] = result
                    device.navigation_executor._executions[execution_id]['progress'] = 100
                    device.navigation_executor._executions[execution_id]['message'] = result.get('message', 'Navigation completed')
                    emit_execution_event(
                        'navigation',
                        execution_id,
                        'completed',
                        device_id=device_id,
                        team_id=team_id,
                        result=result,
                        progress=100,
                        message=result.get('message', 'Navigation completed'),
                    )
                else:
                    # Navigation failed - set status to error
                    device.navigation_executor._executions[execution_id]['status'] = 'error'
                    device.navigation_executor._executions[execution_id]['error'] = result.get('error', 'Navigation failed')
                    device.navigation_executor._executions[execution_id]['result'] = result
                    device.navigation_executor._executions[execution_id]['progress'] = 100
                    device.navigation_executor._executions[execution_id]['message'] = 'Navigation failed'
                    emit_execution_event(
                        'navigation',
                        execution_id,
                        'error',
                        device_id=device_id,
                        team_id=team_id,
                        result=result,
                        error=result.get('error', 'Navigation failed'),
                        progress=100,
                        message='Navigation failed',
                    )
                
        except Exception as e:
            print(f"[@route:host_navigation:navigation_execute] Execution error: {e}")
            import traceback
            traceback.print_exc()
            
            # Update execution state with error
            with device.navigation_executor._lock:
                device.navigation_executor._executions[execution_id]['status'] = 'error'
                device.navigation_executor._executions[execution_id]['error'] = str(e)
                device.navigation_executor._executions[execution_id]['message'] = f'Navigation failed: {str(e)}'
            emit_execution_event(
                'navigation',
                execution_id,
                'error',
                device_id=device_id,
                team_id=team_id,
                error=str(e),
                progress=100,
                message='Navigation failed',
            )
    
    # Start thread
    thread = threading.Thread(target=run_navigation, daemon=True)
    thread.start()
    
    print(f"[@route:host_navigation:navigation_execute] Async execution started: {execution_id}")
    emit_execution_event(
        'navigation',
        execution_id,
        'running',
        device_id=device_id,
        team_id=team_id,
        progress=0,
        message='Navigation started',
    )
        
    return jsonify({'success': True, 'execution_id': execution_id, 'message': 'Navigation started'})
    
@host_navigation_bp.route('/execution/<execution_id>/status', methods=['GET'])
@route_exception_handler()
def navigation_execution_status(execution_id):
    # Get query parameters
    device_id = request.args.get('device_id', 'device1')
    
    # Get host device registry from app context
    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} not found in host'
        }), 404
    
    device = host_devices[device_id]
    
    # Check if device has navigation_executor
    if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have NavigationExecutor initialized'
        }), 500
    
    # Get execution status from NavigationExecutor (not WebWorker)
    # Execution tracking is managed by NavigationExecutor
    status = device.navigation_executor.get_execution_status(execution_id)
    return jsonify(status)
    
@host_navigation_bp.route('/preview/<tree_id>/<target_node_id>', methods=['GET'])
@route_exception_handler()
def navigation_preview(tree_id, target_node_id):
    print(f"[@route:host_navigation:navigation_preview] Getting preview for {target_node_id}")
    
    # Get query parameters
    device_id = request.args.get('device_id', 'device1')
    current_node_id = request.args.get('current_node_id')
    team_id = request.args.get('team_id')
    # Explicit variant from the canvas-selected scope. Canonicalized (supports
    # a composition, see host_navigation_routes.check_navigation_cache).
    # When absent, get_navigation_preview falls back to device.navigation_context.
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    variant = canonical_variant_name(request.args.get('variant'))

    print(f"[@route:host_navigation:navigation_preview] Device: {device_id}, Tree: {tree_id}, Team: {team_id}, Variant: {variant or 'base'}")
    
    # Validate team_id for auto-loading capability
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id query parameter is required for navigation preview'
        }), 400
    
    # Get host device registry from app context
    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({
            'success': False, 
            'error': f'Device {device_id} not found in host'
        }), 404
    
    device = host_devices[device_id]
    
    # Check if device has navigation_executor
    if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have NavigationExecutor initialized'
        }), 500
    
    # Get navigation preview using device's NavigationExecutor with team_id for auto-loading
    result = device.navigation_executor.get_navigation_preview(
        tree_id=tree_id,
        target_node_id=target_node_id,
        current_node_id=current_node_id,
        team_id=team_id,
        variant=variant,
    )
    
    print(f"[@route:host_navigation:navigation_preview] Preview completed: success={result.get('success')}")
    
    return jsonify(result)
    
@host_navigation_bp.route('/cache/check/<tree_id>', methods=['GET'])
@route_exception_handler()
def check_navigation_cache(tree_id):
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400

    # Resolve the variant scope this check should answer for. The unified
    # cache is keyed per-variant (see VARIANT.md §6); without this the check
    # always answers for __base__ while the preview/execute path reads the
    # device's active variant, so server-side "cache exists" lies and the
    # downstream preview blows up with UnifiedCacheError.
    raw_variant = request.args.get('variant')
    variant = raw_variant.strip().lower() if isinstance(raw_variant, str) and raw_variant.strip() else None
    if variant is None:
        device_id = request.args.get('device_id')
        if device_id:
            host_devices = getattr(current_app, 'host_devices', {})
            device = host_devices.get(device_id)
            if device and getattr(device, 'navigation_context', None):
                variant = device.navigation_context.get('variant')

    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    cached_graph = get_cached_unified_graph(tree_id, team_id, variant=variant)

    exists = cached_graph is not None
    nodes_count = len(cached_graph.nodes) if cached_graph else 0
    edges_count = len(cached_graph.edges) if cached_graph else 0

    scope = f"variant={variant}" if variant else "base"
    print(f"[@route:host_navigation:check_navigation_cache] Cache exists for tree {tree_id} ({scope}): {exists}")

    return jsonify({
        'success': True,
        'exists': exists,
        'nodes_count': nodes_count,
        'edges_count': edges_count,
        'variant': variant,
    })
    
def _invalidate_tree_cache_on_host(tree_id, team_id, variant=None):
    """Drop the cached unified graph + preview cache for a tree on this host.

    Single source of truth for host-side cache invalidation, shared by the
    explicit /cache/clear route AND the /cache/update-edge|node routes.

    In-place graph patching was abandoned: it silently diverged from a full
    rebuild. `update-edge` added only the one authored direction (never the
    auto-generated `_reverse` edge) and never re-ran `_create_sibling_shortcuts`,
    and `update-node` shallow-merged the raw frontend node shape over processed
    attrs (is_entry_point, metadata, tree_id, resolved verifications). Across a
    series of edits a host's graph drifted until pathfinding returned a wrong
    truncated path on THAT host only (e.g. a goto preview showing just the last
    hop instead of entry → … → target). Invalidating forces a correct lazy
    rebuild from the DB on the next preview / populate / take-control. See
    docs/agent/navigation/NAVIGATION.md §6.

    Returns the list of device_ids whose in-memory graph was dropped.
    """
    from shared.src.lib.utils.navigation_cache import clear_unified_cache
    clear_unified_cache(tree_id, team_id, variant=variant)

    host_devices = getattr(current_app, 'host_devices', {})
    cleared_devices = []
    for device_id, device in host_devices.items():
        ne = getattr(device, 'navigation_executor', None)
        if not ne:
            continue
        # Whole-tree invalidation (variant is None) blanks the snapshot the
        # executor trusts; a variant-scoped clear only drops that variant's
        # precomputed previews (each read site re-fetches with its own variant).
        if variant is None:
            if ne.unified_graph:
                ne.unified_graph = None
                cleared_devices.append(device_id)
            ne.clear_preview_cache(tree_id, team_id)
        else:
            ne.clear_preview_cache(tree_id, team_id, variant=variant)
    return cleared_devices


@host_navigation_bp.route('/cache/update-edge', methods=['POST'])
@route_exception_handler()
def update_edge_in_cache():
    data = request.get_json() or {}
    edge_data = data.get('edge')
    tree_id = data.get('tree_id')
    team_id = request.args.get('team_id')
    
    if not edge_data or not tree_id or not team_id:
        return jsonify({
            'success': False,
            'error': 'edge, tree_id, and team_id are required'
        }), 400
    
    edge_id = edge_data.get('id')
    source_node = edge_data.get('source_node_id')
    target_node = edge_data.get('target_node_id')
    
    if not edge_id or not source_node or not target_node:
        return jsonify({
            'success': False,
            'error': 'edge must have id, source_node_id, and target_node_id'
        }), 400
    
    # Resolve to root tree (cache is always stored under root tree ID)
    from shared.src.lib.database.navigation_trees_db import _get_root_tree_id
    root_tree_id = _get_root_tree_id(tree_id, team_id)
    
    if not root_tree_id:
        root_tree_id = tree_id  # Fallback to original tree_id
    
    # Get the cached graph (silent=True to avoid logging cache misses)
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    
    cached_graph = get_cached_unified_graph(root_tree_id, team_id, silent=True)
    
    # If no cache exists, silently skip (cache only created on take-control)
    if not cached_graph:
        return jsonify({
            'success': True,
            'message': f'No cache for tree {tree_id} - update skipped (will rebuild on next take-control)',
            'cache_exists': False
        })
    
    # Cache exists - log the update
    print(f"[@route:host_navigation:update_edge_in_cache] 🔧 Update Request:")
    print(f"  → Edge ID: {edge_id}")
    print(f"  → Tree ID (requested): {tree_id}")
    print(f"  → Team ID: {team_id}")
    print(f"  → Source: {source_node} → Target: {target_node}")
    if root_tree_id != tree_id:
        print(f"  🔗 Resolved to ROOT tree: {root_tree_id}")
    
    # Invalidate rather than patch in place. In-place edge patching diverged
    # from a full rebuild (no auto-generated reverse edge, no recomputed sibling
    # shortcuts), so the host graph drifted and pathfinding truncated the path on
    # this host only. Drop the cached graph; it rebuilds correctly from the DB on
    # the next preview / take-control.
    cleared_devices = _invalidate_tree_cache_on_host(root_tree_id, team_id)
    print(f"[@route:host_navigation:update_edge_in_cache] ✅ Edge {edge_id} change → cache invalidated (file + {len(cleared_devices)} NavigationExecutor instances)")

    return jsonify({
        'success': True,
        'message': f'Edge {edge_id} change invalidated cache for tree {tree_id}',
        'invalidated_devices': cleared_devices,
        'cache_exists': True
    })
    
@host_navigation_bp.route('/cache/update-node', methods=['POST'])
@route_exception_handler()
def update_node_in_cache():
    data = request.get_json() or {}
    node_data = data.get('node')
    tree_id = data.get('tree_id')
    team_id = request.args.get('team_id')
    
    if not node_data or not tree_id or not team_id:
        return jsonify({
            'success': False,
            'error': 'node, tree_id, and team_id are required'
        }), 400
    
    node_id = node_data.get('id')
    if not node_id:
        return jsonify({
            'success': False,
            'error': 'node must have id'
        }), 400
    
    # Resolve to root tree (cache is always stored under root tree ID)
    from shared.src.lib.database.navigation_trees_db import _get_root_tree_id
    root_tree_id = _get_root_tree_id(tree_id, team_id)
    
    if not root_tree_id:
        root_tree_id = tree_id  # Fallback to original tree_id
    
    # Get the cached graph (silent=True to avoid logging cache misses)
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
    
    cached_graph = get_cached_unified_graph(root_tree_id, team_id, silent=True)
    
    # If no cache exists, silently skip (cache only created on take-control)
    if not cached_graph:
        return jsonify({
            'success': True,
            'message': f'No cache for tree {tree_id} - update skipped (will rebuild on next take-control)',
            'cache_exists': False
        })
    
    # Cache exists - log the update
    print(f"[@route:host_navigation:update_node_in_cache] 🔧 Update Request:")
    print(f"  → Node ID: {node_id}")
    print(f"  → Tree ID (requested): {tree_id}")
    print(f"  → Team ID: {team_id}")
    if root_tree_id != tree_id:
        print(f"  🔗 Resolved to ROOT tree: {root_tree_id}")
    
    # Invalidate rather than patch in place. A shallow .update() merged the raw
    # frontend node shape over the processed graph attrs (is_entry_point,
    # metadata, tree_id, resolved verifications), silently corrupting the node on
    # this host. Drop the cached graph; it rebuilds correctly from the DB on the
    # next preview / take-control.
    cleared_devices = _invalidate_tree_cache_on_host(root_tree_id, team_id)
    print(f"[@route:host_navigation:update_node_in_cache] ✅ Node {node_id} change → cache invalidated (file + {len(cleared_devices)} NavigationExecutor instances)")

    return jsonify({
        'success': True,
        'message': f'Node {node_id} change invalidated cache for tree {tree_id}',
        'invalidated_devices': cleared_devices,
        'cache_exists': True
    })
    
@host_navigation_bp.route('/cache/clear/<tree_id>', methods=['POST'])
@route_exception_handler()
def clear_navigation_cache_for_tree(tree_id):
    """Invalidate cached navigation graph(s) for a tree on this host.

    Query params:
      team_id  — required
      variant  — optional. When present, only that variant's cache entry is
                 dropped (other variants and base remain). When absent (or
                 empty string), every variant entry for the tree is dropped —
                 used after base-row mutations that affect fall-through views.
    """
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400

    raw_variant = request.args.get('variant')
    variant = raw_variant.strip().lower() if isinstance(raw_variant, str) and raw_variant.strip() else None

    # Shared invalidation: drops the file graph cache, blanks each executor's
    # in-memory snapshot (whole-tree clears only), and clears precomputed
    # previews. See _invalidate_tree_cache_on_host for why patching was dropped.
    cleared_devices = _invalidate_tree_cache_on_host(tree_id, team_id, variant=variant)

    scope_label = f"variant={variant}" if variant else "all variants"
    print(f"[@route:host_navigation:clear_navigation_cache_for_tree] ✅ Cache cleared for tree {tree_id} ({scope_label}, file cache + {len(cleared_devices)} NavigationExecutor instances)")

    return jsonify({
        'success': True,
        'message': f'Cache cleared for tree {tree_id} ({scope_label})',
        'variant': variant,
        'cleared_devices': cleared_devices
    })
    
@host_navigation_bp.route('/cache/populate/<tree_id>', methods=['POST'])
@route_exception_handler()
def populate_navigation_cache(tree_id):
    print(f"[@route:host_navigation:populate_navigation_cache] Populating cache for tree: {tree_id}")

    # Get request data
    data = request.get_json() or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    all_trees_data = data.get('all_trees_data', [])
    force_repopulate = data.get('force_repopulate', False)

    # Validate required parameters
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400

    if not all_trees_data:
        return jsonify({
            'success': False,
            'error': 'all_trees_data is required'
        }), 400

    # Resolve variant scope to populate. Caches are keyed per-variant; without
    # this, callers proxying from /preview or /execute would always (re)populate
    # __base__ while the read path queries the device's active variant.
    raw_variant = request.args.get('variant')
    variant = raw_variant.strip().lower() if isinstance(raw_variant, str) and raw_variant.strip() else None
    if variant is None:
        device_id = request.args.get('device_id')
        if device_id:
            host_devices_lookup = getattr(current_app, 'host_devices', {})
            device_lookup = host_devices_lookup.get(device_id)
            if device_lookup and getattr(device_lookup, 'navigation_context', None):
                variant = device_lookup.navigation_context.get('variant')

    # Check if cache already exists (protection against re-population)
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph, populate_unified_cache, refresh_cache_timestamp
    existing_cache = get_cached_unified_graph(tree_id, team_id, variant=variant)

    if existing_cache and not force_repopulate:
        # Refresh timestamp to prevent TTL expiry between this check and next use
        refresh_cache_timestamp(tree_id, team_id, variant=variant)
        scope = f"variant={variant}" if variant else "base"
        print(f"[@route:host_navigation:populate_navigation_cache] Cache already exists for tree {tree_id} ({scope}), skipping re-population (timestamp refreshed)")

        # ✅ SYNC: Ensure all NavigationExecutor instances are synced with cache
        host_devices = getattr(current_app, 'host_devices', {})
        for device_id, device in host_devices.items():
            if hasattr(device, 'navigation_executor') and device.navigation_executor:
                if not device.navigation_executor.unified_graph:
                    device.navigation_executor.unified_graph = existing_cache
                    print(f"[@route:host_navigation:populate_navigation_cache] Synced NavigationExecutor for device {device_id} with existing cache")

        return jsonify({
            'success': True,
            'nodes_count': len(existing_cache.nodes),
            'edges_count': len(existing_cache.edges),
            'message': f'Cache already exists for tree {tree_id}',
            'already_cached': True,
            'variant': variant,
        })

    # For non-base populates, resolve variant overrides from DB. populate_unified_cache
    # without overrides would cache *base* content under the variant key — making
    # variant pathfinding silently serve base routes.
    variant_node_overrides = None
    variant_edge_overrides = None
    if variant:
        from shared.src.lib.utils.supabase_utils import get_supabase_client
        from shared.src.lib.database.userinterface_db import get_variant
        # Resolve userinterface_id from the actual root tree — subtrees can carry a
        # NULL userinterface_id in DB, so look up by `is_root_tree=True` entry in
        # all_trees_data, fall back to direct query if missing.
        root_tree_id_lookup = None
        for tree_data in all_trees_data:
            ti = tree_data.get('tree_info') or {}
            if ti.get('is_root_tree'):
                root_tree_id_lookup = tree_data.get('tree_id')
                break
        if not root_tree_id_lookup:
            root_tree_id_lookup = tree_id
        userinterface_id = None
        try:
            tree_row = get_supabase_client().table('navigation_trees') \
                .select('userinterface_id') \
                .eq('id', root_tree_id_lookup).eq('team_id', team_id).limit(1).execute()
            if tree_row.data:
                userinterface_id = tree_row.data[0].get('userinterface_id')
        except Exception as lookup_exc:
            print(f"[@route:host_navigation:populate_navigation_cache] Failed to look up userinterface_id for tree {root_tree_id_lookup}: {lookup_exc}")
        if userinterface_id:
            variant_row = get_variant(team_id, userinterface_id, variant)
            if variant_row:
                variant_node_overrides = variant_row.get('node_overrides') or {}
                variant_edge_overrides = variant_row.get('edge_overrides') or {}
            else:
                print(f"[@route:host_navigation:populate_navigation_cache] Variant '{variant}' not found in DB for userinterface {userinterface_id} — populating with base content under variant key")
        else:
            print(f"[@route:host_navigation:populate_navigation_cache] No userinterface_id resolvable for tree {tree_id} — variant overrides skipped")

    # Populate unified cache in host process
    unified_graph = populate_unified_cache(
        tree_id, team_id, all_trees_data,
        variant_node_overrides=variant_node_overrides,
        variant_edge_overrides=variant_edge_overrides,
        variant=variant,
    )
    
    if unified_graph:
        action = 'Re-populated' if force_repopulate else 'Populated'
        print(f"[@route:host_navigation:populate_navigation_cache] {action} cache: {len(unified_graph.nodes)} nodes, {len(unified_graph.edges)} edges")
        
        # ✅ UPDATE: Sync all NavigationExecutor instances with the cached graph
        host_devices = getattr(current_app, 'host_devices', {})
        for device_id, device in host_devices.items():
            if hasattr(device, 'navigation_executor') and device.navigation_executor:
                device.navigation_executor.unified_graph = unified_graph
                print(f"[@route:host_navigation:populate_navigation_cache] Updated NavigationExecutor for device {device_id}")
        
        return jsonify({
            'success': True,
            'nodes_count': len(unified_graph.nodes),
            'edges_count': len(unified_graph.edges),
            'message': f'Cache {action.lower()} for tree {tree_id}',
            'repopulated': force_repopulate
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to populate unified cache'
        }), 500
        
@host_navigation_bp.route('/validation_sequence', methods=['POST'])
@route_exception_handler()
def get_validation_sequence():
    print(f"[@route:host_navigation:get_validation_sequence] Getting validation sequence")
    
    # Get request data
    data = request.get_json() or {}
    tree_id = data.get('tree_id')
    team_id = data.get('team_id')
    
    if not tree_id:
        return jsonify({
            'success': False,
            'error': 'tree_id is required'
        }), 400
        
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
    
    print(f"[@route:host_navigation:get_validation_sequence] Tree: {tree_id}, Team: {team_id}")
    
    # Get validation sequence using pathfinding service
    from backend_host.src.services.navigation.navigation_pathfinding import find_optimal_edge_validation_sequence
    
    validation_sequence = find_optimal_edge_validation_sequence(tree_id, team_id)
    
    if validation_sequence:
        print(f"[@route:host_navigation:get_validation_sequence] Generated {len(validation_sequence)} validation steps")
        return jsonify({
            'success': True,
            'sequence': validation_sequence,
            'total_steps': len(validation_sequence)
        })
    else:
        print(f"[@route:host_navigation:get_validation_sequence] No validation sequence found")
        return jsonify({
            'success': False,
            'error': 'No validation sequence found - tree may be empty or have no traversable edges'
        }), 400
        
@host_navigation_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for host navigation service"""
    return jsonify({
        'success': True,
        'message': 'Host navigation service is running'
    })

# ========================================
# BACKGROUND EXECUTION THREAD
# ========================================

def _execute_navigation_thread(
    device,
    execution_id: str,
    tree_id: str,
    userinterface_name: str,
    target_node_id: str,
    target_node_label: str,
    current_node_id: str,
    frontend_sent_position: bool,
    image_source_url: str,
    team_id: str
):
    """Execute navigation in background thread with progress tracking"""
    import sys
    import io
    import time
    
    # Capture logs for single navigation execution
    log_buffer = io.StringIO()
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    
    class Tee:
        def __init__(self, *streams):
            self.streams = streams
        def write(self, data):
            for stream in self.streams:
                stream.write(data)
                stream.flush()
        def flush(self):
            for stream in self.streams:
                stream.flush()
    
    try:
        # Redirect stdout/stderr to BOTH terminal and buffer
        sys.stdout = Tee(old_stdout, log_buffer)
        sys.stderr = Tee(old_stderr, log_buffer)
        
        # Update status
        with device.navigation_executor._lock:
            device.navigation_executor._executions[execution_id]['message'] = 'Executing navigation...'
            device.navigation_executor._executions[execution_id]['progress'] = 50
        
        # ✅ Execute navigation through ExecutionOrchestrator for consistent logging
        from backend_host.src.orchestrator import ExecutionOrchestrator
        import asyncio
        result = asyncio.run(ExecutionOrchestrator.execute_navigation(
            device=device,
            tree_id=tree_id,
            userinterface_name=userinterface_name,
            target_node_id=target_node_id,
            target_node_label=target_node_label,
            current_node_id=current_node_id,
            frontend_sent_position=frontend_sent_position,
            image_source_url=image_source_url,
            team_id=team_id,
            context=None,
        ))
        
        # Stop log capture and add logs to result
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        captured_logs = log_buffer.getvalue()
        if captured_logs:
            result['logs'] = captured_logs
        
        # Update with result
        with device.navigation_executor._lock:
            # DEBUG: Check what result actually contains
            print(f"[@route:DEBUG] result.get('success') = {result.get('success')}, result keys = {result.keys()}")
            print(f"[@route:DEBUG] result['success'] = {result.get('success', 'KEY_MISSING')}")
            if 'error' in result:
                print(f"[@route:DEBUG] result['error'] = {result['error']}")
            
            if result.get('success'):
                device.navigation_executor._executions[execution_id]['status'] = 'completed'
                device.navigation_executor._executions[execution_id]['result'] = result
                device.navigation_executor._executions[execution_id]['progress'] = 100
                device.navigation_executor._executions[execution_id]['message'] = 'Navigation completed'
                emit_execution_event(
                    'navigation',
                    execution_id,
                    'completed',
                    device_id=getattr(device, 'device_id', None),
                    team_id=team_id,
                    result=result,
                    progress=100,
                    message='Navigation completed',
                )
            else:
                device.navigation_executor._executions[execution_id]['status'] = 'error'
                device.navigation_executor._executions[execution_id]['error'] = result.get('error', 'Navigation failed')
                device.navigation_executor._executions[execution_id]['result'] = result
                device.navigation_executor._executions[execution_id]['progress'] = 100
                device.navigation_executor._executions[execution_id]['message'] = 'Navigation failed'
                emit_execution_event(
                    'navigation',
                    execution_id,
                    'error',
                    device_id=getattr(device, 'device_id', None),
                    team_id=team_id,
                    result=result,
                    error=result.get('error', 'Navigation failed'),
                    progress=100,
                    message='Navigation failed',
                )
    
    except Exception as e:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
        # Update with error
        with device.navigation_executor._lock:
            device.navigation_executor._executions[execution_id]['status'] = 'error'
            device.navigation_executor._executions[execution_id]['error'] = str(e)
            device.navigation_executor._executions[execution_id]['progress'] = 100
            device.navigation_executor._executions[execution_id]['message'] = f'Navigation error: {str(e)}'
        emit_execution_event(
            'navigation',
            execution_id,
            'error',
            device_id=getattr(device, 'device_id', None),
            team_id=team_id,
            error=str(e),
            progress=100,
            message='Navigation error',
        )
    finally:
        # Always restore stdout/stderr
        if sys.stdout != old_stdout:
            sys.stdout = old_stdout
        if sys.stderr != old_stderr:
            sys.stderr = old_stderr


@host_navigation_bp.route('/localize', methods=['POST'])
@route_exception_handler()
def navigation_localize():
    """Identify which node the live device screen matches (Localize).

    Synchronous (fast: one capture + in-memory fingerprint ranking). Returns
    ranked candidate nodes + how many were excluded, scoped to the active variant.
    tree_id is resolved from userinterface_name by the executor.
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id') or data.get('team_id')
    userinterface_name = data.get('userinterface_name')
    raw_variant = data.get('variant')
    variant = (raw_variant or '').strip().lower() or None if isinstance(raw_variant, str) else None

    print(f"[@route:host_navigation:localize] device={device_id} "
          f"team={team_id} ui={userinterface_name} variant={variant or 'base'}")

    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if not userinterface_name:
        return jsonify({'success': False, 'error': 'userinterface_name is required'}), 400

    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found in host'}), 404
    device = host_devices[device_id]

    # Stamp the run scope so the executor resolves the right variant fingerprints.
    if not hasattr(device, 'navigation_context') or device.navigation_context is None:
        device.navigation_context = {}
    device.navigation_context['variant'] = variant

    if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
        return jsonify({'success': False, 'error': f'Device {device_id} has no NavigationExecutor'}), 500

    result = device.navigation_executor.localize(team_id, userinterface_name)
    return jsonify(result)
