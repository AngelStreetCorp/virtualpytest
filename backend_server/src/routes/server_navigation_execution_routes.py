"""
Server Navigation Execution Routes

This module provides API endpoints for navigation execution using the standardized
NavigationExecutor class. These endpoints can be used by:
- Frontend components (via fetch calls)
- Python scripts (via direct API calls)
- External integrations

The endpoints use the same NavigationExecutor that can be used directly in Python code.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from shared.src.lib.utils.app_utils import get_team_id
from  backend_server.src.lib.utils.route_utils import proxy_to_host, proxy_to_host_with_params

# Create blueprint
server_navigation_execution_bp = Blueprint('server_navigation_execution', __name__, url_prefix='/server/navigation')


@server_navigation_execution_bp.route('/execute/<tree_id>', methods=['POST'])
@handle_route_exceptions('navigation_execution:execute_navigation')
def execute_navigation(tree_id):
    """
    Execute navigation using standardized NavigationExecutor
    
    Required JSON payload (provide EXACTLY ONE of target_node_id or target_node_label):
    
    Option 1 - Navigate by UUID:
    {
        "target_node_id": "46854a27-57d2-43ee-bb8d-925b29b83843",
        "host_name": "...",
        "device_id": "optional_device_id",
        "current_node_id": "optional_current_node",
        "userinterface_name": "interface_name",
        "image_source_url": "optional_image_source"
    }
    
    Option 2 - Navigate by label:
    {
        "target_node_label": "home",
        "host_name": "...",
        "device_id": "optional_device_id",
        "current_node_id": "optional_current_node",
        "userinterface_name": "interface_name",
        "image_source_url": "optional_image_source"
    }
    """
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
    
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    team_id = request.args.get('team_id')
    current_node_id = data.get('current_node_id')
    image_source_url = data.get('image_source_url')
    userinterface_name = data.get('userinterface_name')  # MANDATORY for reference resolution

    # Run scope: lowercase variant name registered in userinterface_variants,
    # or None for base. Empty/whitespace coerce to None. Forwarded to host so
    # the row in execution_results carries the same label and the metrics
    # trigger keys edge_metrics/node_metrics on (..., variant).
    raw_variant = data.get('variant')
    variant = (raw_variant or '').strip().lower() or None if isinstance(raw_variant, str) else None

    # Interactive Editor Goto runs flag is_test=true so per-step recording
    # excludes them from edge_metrics / node_metrics aggregates.
    is_test = bool(data.get('is_test', False))

    # Verification mode: 'end' (default) | 'each' | 'auto'. Controls which
    # steps run verify_node on their destination during goto. Independent
    # of KPI queueing.
    verification_mode = (data.get('verification_mode') or 'end').strip().lower()
    if verification_mode not in ('end', 'each', 'auto'):
        verification_mode = 'end'
    
    # Validate required parameters
    if not host_name:
        return jsonify({
            'success': False,
            'error': 'host_name is required'
        }), 400
    
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
    
    if not userinterface_name:
        return jsonify({
            'success': False,
            'error': 'userinterface_name is required for reference resolution'
        }), 400
    
    # Check cache exists - populate if missing (navigation can work without exclusive control)
    print(f"[@route:navigation_execution:execute_navigation] Navigation execution for tree {tree_id}, team_id {team_id}")

    # Verify cache exists before execution (quick check - should be fast).
    # Pass device_id + variant so the host check is scoped to the variant the
    # execute path will read — otherwise we'd verify __base__ exists while the
    # device runs against a missing variant cache.
    from  backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
    check_params = {'team_id': team_id}
    if device_id:
        check_params['device_id'] = device_id
    if variant:
        check_params['variant'] = variant
    cache_check_result, _ = proxy_to_host_with_params(f'/host/navigation/cache/check/{tree_id}', 'GET', None, check_params, timeout=5)

    if cache_check_result and cache_check_result.get('success') and cache_check_result.get('exists'):
        print(f"[@route:navigation_execution:execute_navigation] ✅ Cache exists for tree {tree_id}")
    else:
        print(f"[@route:navigation_execution:execute_navigation] ❌ Cache missing for tree {tree_id} - populating now...")

        # Cache missing - populate it (doesn't require device locking, just tree data loading).
        # Pass explicit variant: the host's device.navigation_context['variant'] hasn't been
        # updated yet (that happens inside /host/navigation/execute, which runs later in this
        # flow), so device-context resolution would race and populate the wrong variant key.
        from backend_server.src.routes.server_control_routes import populate_navigation_cache_for_control
        cache_populated = populate_navigation_cache_for_control(
            tree_id, team_id, host_name, device_id=device_id, variant=variant
        )

        if not cache_populated:
            return jsonify({
                'success': False,
                'error': f'Failed to populate navigation cache for tree {tree_id}. Check server logs for details.'
            }), 500

        print(f"[@route:navigation_execution:execute_navigation] ✅ Cache populated successfully for tree {tree_id}")

        # Verify cache was populated
        cache_check_result, _ = proxy_to_host_with_params(f'/host/navigation/cache/check/{tree_id}', 'GET', None, check_params, timeout=5)
        if not (cache_check_result and cache_check_result.get('success') and cache_check_result.get('exists')):
            return jsonify({
                'success': False,
                'error': f'Cache population failed verification for tree {tree_id}'
            }), 500
    
    # Proxy to host navigation execution endpoint
    execution_payload = {
        'tree_id': tree_id,  # CRITICAL: Include tree_id in body
        'target_node_id': target_node_id,
        'target_node_label': target_node_label,
        'device_id': device_id,
        'current_node_id': current_node_id,
        'image_source_url': image_source_url,
        'host_name': host_name,
        'userinterface_name': userinterface_name,
        'variant': variant,
        'is_test': is_test,
        'verification_mode': verification_mode,
    }
    
    # Pass team_id as query parameter to host
    query_params = {}
    if team_id:
        query_params['team_id'] = team_id
    
    # Navigation always uses web actions (Playwright) - execute synchronously
    # Use longer timeout for sync execution (navigation can take time with waits)
    print(f"[@route:navigation_execution:execute_navigation] Using 120s timeout for synchronous navigation execution")
    timeout = 120  # Navigation can be long with multiple edges + wait times
    
    response_data, status_code = proxy_to_host_with_params(f'/host/navigation/execute/{tree_id}', 'POST', execution_payload, query_params, timeout=timeout)
    
    print(f"[@route:navigation_execution:execute_navigation] Navigation result: success={response_data.get('success')}")
    
    return jsonify(response_data), status_code
    
@server_navigation_execution_bp.route('/execution/<execution_id>/status', methods=['GET'])
@handle_route_exceptions('navigation_execution:get_navigation_execution_status')
def get_navigation_execution_status(execution_id):
    """
    Get status of async navigation execution
    
    Query parameters:
    - device_id: Device ID
    - host_name: Host name (required)
    """
    print(f"[@route:navigation_execution:get_status] Getting status for execution {execution_id}")
    
    device_id = request.args.get('device_id')
    host_name = request.args.get('host_name')
    
    # Validate required parameters
    if not host_name:
        return jsonify({
            'success': False,
            'error': 'host_name query parameter is required'
        }), 400
    
    # Proxy to host status endpoint
    query_params = {}
    if device_id:
        query_params['device_id'] = device_id
    
    response_data, status_code = proxy_to_host_with_params(
        f'/host/navigation/execution/{execution_id}/status',
        'GET',
        None,
        query_params,
        timeout=5
    )
    
    return jsonify(response_data), status_code
    
@server_navigation_execution_bp.route('/preview/<tree_id>/<node_id>', methods=['GET'])
@handle_route_exceptions('navigation_execution:get_navigation_preview_with_executor')
def get_navigation_preview_with_executor(tree_id, node_id):
    """
    Get navigation preview using NavigationExecutor
    
    Query parameters:
    - current_node_id: optional current node for pathfinding
    - host_name: required host name for executor initialization
    - device_id: optional device ID
    - team_id: optional team ID
    """
    print(f"[@route:navigation_execution:get_navigation_preview_with_executor] Getting preview for navigation to {node_id} in tree {tree_id}")
    
    current_node_id = request.args.get('current_node_id')
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id')
    team_id = request.args.get('team_id')
    # Canvas-selected variant from the frontend goto panel. Forwarded to the
    # cache check, cache populate, and host preview so all three resolve to
    # the same variant-scoped unified graph. When None, the host falls back
    # to device.navigation_context (base by default).
    variant = request.args.get('variant')

    # Validate required parameters
    if not host_name:
        return jsonify({
            'success': False,
            'error': 'host_name query parameter is required'
        }), 400

    # Check cache exists - populate if missing (navigation can work without exclusive control).
    # Pass device_id so the host scopes the check to the device's active variant —
    # without it the check answers for __base__ while the preview path reads the
    # variant cache and surfaces "Navigation tree X not loaded".
    check_params = {'team_id': team_id}
    if device_id:
        check_params['device_id'] = device_id
    if variant:
        check_params['variant'] = variant
    cache_check_result, _ = proxy_to_host_with_params(f'/host/navigation/cache/check/{tree_id}', 'GET', None, check_params, timeout=10)

    if cache_check_result and cache_check_result.get('success') and cache_check_result.get('exists'):
        print(f"[@route:navigation_execution:get_navigation_preview_with_executor] ✅ Cache exists for tree {tree_id}")
    else:
        print(f"[@route:navigation_execution:get_navigation_preview_with_executor] ❌ Cache missing for tree {tree_id} - populating now...")

        # Cache missing - populate it (doesn't require device locking, just tree data loading)
        from backend_server.src.routes.server_control_routes import populate_navigation_cache_for_control
        cache_populated = populate_navigation_cache_for_control(tree_id, team_id, host_name, device_id=device_id, variant=variant)

        if not cache_populated:
            return jsonify({
                'success': False,
                'error': f'Failed to populate navigation cache for tree {tree_id}. Check server logs for details.'
            }), 500

        print(f"[@route:navigation_execution:get_navigation_preview_with_executor] ✅ Cache populated successfully for tree {tree_id}")

        # Verify cache was populated
        cache_check_result, _ = proxy_to_host_with_params(f'/host/navigation/cache/check/{tree_id}', 'GET', None, check_params, timeout=10)
        if not (cache_check_result and cache_check_result.get('success') and cache_check_result.get('exists')):
            return jsonify({
                'success': False,
                'error': f'Cache population failed verification for tree {tree_id}'
            }), 500
    
    # Create minimal host configuration for preview
    host = {'host_name': host_name}
    
    # Proxy to host navigation preview endpoint
    query_params = {
        'device_id': device_id,
        'current_node_id': current_node_id,
        'team_id': team_id,
        'variant': variant,
    }

    # Remove None values
    query_params = {k: v for k, v in query_params.items() if v is not None}
    
    response_data, status_code = proxy_to_host_with_params(f'/host/navigation/preview/{tree_id}/{node_id}', 'GET', None, query_params, timeout=60)
    
    print(f"[@route:navigation_execution:get_navigation_preview_with_executor] Preview result: success={response_data.get('success')}")
    
    return jsonify(response_data), status_code
    
@server_navigation_execution_bp.route('/batch-execute', methods=['POST'])
@handle_route_exceptions('navigation_execution:batch_execute_navigation')
def batch_execute_navigation():
    """
    Execute multiple navigation operations in sequence
    
    Expected JSON payload:
    {
        "host": {"host_name": "...", "device_model": "...", ...},
        "device_id": "optional_device_id",
        "team_id": "optional_team_id",
        "navigations": [
            {
                "tree_id": "tree1",
                "target_node_id": "node1",
                "current_node_id": "optional_current"
            },
            {
                "tree_id": "tree2", 
                "target_node_id": "node2"
            }
        ]
    }
    """
    print(f"[@route:navigation_execution:batch_execute_navigation] Starting batch navigation execution")
    
    data = request.get_json() or {}
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    team_id = request.args.get('team_id')
    navigations = data.get('navigations', [])
    
    # Validate required parameters
    if not host_name:
        return jsonify({
            'success': False,
            'error': 'host_name is required'
        }), 400
    
    if not navigations:
        return jsonify({
            'success': False,
            'error': 'navigations array is required'
        }), 400
    
    if not team_id:
        return jsonify({
            'success': False,
            'error': 'team_id is required'
        }), 400
    
    # Ensure unified cache is populated for all trees in batch
    from backend_server.src.routes.server_control_routes import populate_navigation_cache_for_control

    unique_tree_ids = list(set(nav.get('tree_id') for nav in navigations if nav.get('tree_id')))
    for tree_id in unique_tree_ids:
        print(f"[@route:navigation_execution:batch_execute_navigation] Ensuring cache for tree {tree_id}")
        cache_populated = populate_navigation_cache_for_control(tree_id, team_id, host_name)
        if not cache_populated:
            return jsonify({
                'success': False,
                'error': f'Failed to populate unified navigation cache for tree {tree_id}. Tree may need to be loaded first.'
            }), 400
    
    # Proxy navigation execution to host
    from  backend_server.src.lib.utils.route_utils import proxy_to_host
    from shared.src.lib.utils.app_utils import get_team_id
    
    results = []
    successful_navigations = 0
    
    for i, navigation in enumerate(navigations):
        tree_id = navigation.get('tree_id')
        target_node_id = navigation.get('target_node_id')
        current_node_id = navigation.get('current_node_id')
        # Variant: per-navigation override falls back to batch-level setting
        raw_nav_variant = navigation.get('variant', data.get('variant'))
        nav_variant = (raw_nav_variant or '').strip().lower() or None if isinstance(raw_nav_variant, str) else None

        if not tree_id or not target_node_id:
            result = {
                'success': False,
                'error': 'tree_id and target_node_id are required for each navigation',
                'navigation_index': i
            }
        else:
            print(f"[@route:navigation_execution:batch_execute_navigation] Executing navigation {i+1}/{len(navigations)}: {tree_id} -> {target_node_id} (variant={nav_variant or 'base'})")

            # Per-navigation verification_mode override falls back to batch-level
            raw_nav_mode = (navigation.get('verification_mode')
                            or data.get('verification_mode') or 'end')
            nav_verification_mode = raw_nav_mode.strip().lower() if isinstance(raw_nav_mode, str) else 'end'
            if nav_verification_mode not in ('end', 'each', 'auto'):
                nav_verification_mode = 'end'

            # Proxy to host for actual navigation execution
            batch_payload = {
                'tree_id': tree_id,  # CRITICAL: Include tree_id in body
                'target_node_id': target_node_id,  # CRITICAL: Include target_node_id
                'userinterface_name': userinterface_name,  # CRITICAL: Include userinterface_name
                'device_id': device_id,
                'current_node_id': current_node_id,
                'host_name': host_name,
                'variant': nav_variant,
                'verification_mode': nav_verification_mode,
            }
            
            # Pass team_id as query parameter to host
            batch_query_params = {}
            if team_id:
                batch_query_params['team_id'] = team_id
            
            proxy_result, proxy_status = proxy_to_host_with_params(f'/host/navigation/execute/{tree_id}', 'POST', batch_payload, batch_query_params, timeout=180)
            
            result = proxy_result if proxy_result else {'success': False, 'error': 'Host proxy failed'}
            result['navigation_index'] = i
            
            if result.get('success'):
                successful_navigations += 1
        
        results.append(result)
        
        # If navigation failed and we want to stop on first failure
        if not result.get('success'):
            print(f"[@route:navigation_execution:batch_execute_navigation] Navigation {i+1} failed, continuing with next...")
    
    overall_success = successful_navigations == len(navigations)
    
    print(f"[@route:navigation_execution:batch_execute_navigation] Batch completed: {successful_navigations}/{len(navigations)} successful")
    
    return jsonify({
        'success': overall_success,
        'total_navigations': len(navigations),
        'successful_navigations': successful_navigations,
        'failed_navigations': len(navigations) - successful_navigations,
        'results': results,
        'message': f'Batch navigation completed: {successful_navigations}/{len(navigations)} successful'
    })
    
# Cache should already be populated by take control - no need for redundant population 