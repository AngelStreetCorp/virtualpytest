"""
Host Script Routes - Execute scripts on host device using device script executor
"""
import json
from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from  backend_host.src.lib.utils.host_utils import get_device_by_id

host_script_bp = Blueprint('host_script', __name__, url_prefix='/host')

@host_script_bp.route('/script/execute', methods=['POST'])
@route_exception_handler()
def _execute_script():
    data = request.get_json()
    
    script_name = data.get('script_name')
    device_id = data.get('device_id')
    # Virtual script: DB-stored source materialized to a temp file before launch.
    virtual_script_id = data.get('virtual_script_id')
    # Team scope for resolving the virtual script + its shared libraries
    # (_script_libs). Optional; executor falls back to DEFAULT_TEAM_ID.
    team_id = data.get('team_id') or None
    parameters = data.get('parameters', '')
    trigger = data.get('trigger') or None
    environment = data.get('environment') or None
    # Server/frontend versions forwarded by the server route (host version is
    # read locally by the executor). Persisted into the run metadata.
    versions = data.get('versions') if isinstance(data.get('versions'), dict) else None
    # Optional manual device info merged into the run's metadata.info.
    device_info = data.get('device_info') if isinstance(data.get('device_info'), dict) else None
    # Build callback URL directly (always points to server)
    from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers
    callback_url = buildServerUrl('server/script/taskComplete')
    task_id = data.get('task_id')

    # Optional script identity (prefix / display_name) — resolved by frontend
    # (priority 1) or server fallback (priority 2). Forwarded to the child
    # subprocess via env vars by ScriptExecutor.
    identity_override = {}
    if data.get('prefix'):
        identity_override['prefix'] = data['prefix']
    if data.get('display_name'):
        identity_override['display_name'] = data['display_name']
    
    if not script_name or not device_id:
        return jsonify({
            'success': False,
            'error': 'script_name and device_id required'
        }), 400
    
    print(f"[@route:host_script:_execute_script] Executing {script_name} on {device_id} with parameters: {parameters}")
    
    # Create shared script executor with device context
    from shared.src.lib.executors.script_executor import ScriptExecutor
    from backend_host.src.lib.utils.host_utils import get_host_instance, get_device_by_id
    
    try:
        host = get_host_instance()
        
        # Get actual device model
        device = get_device_by_id(device_id)
        device_model = device.device_model if device else "unknown"
        
        script_executor = ScriptExecutor(
            script_name=script_name,  # Pass script name
            host_name=host.host_name,
            device_id=device_id,
            device_model=device_model  # Use actual device model
        )
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to create script executor: {str(e)}'
        }), 500
    
    if task_id:
        print(f"[@route:host_script:_execute_script] CALLBACK PREP: Async execution for task {task_id}")
        # Execute async with callback
        import threading
        def execute_async():
            # Track whether the server completion callback reached the server. The
            # callback is what releases the server-side device lock, so we must
            # guarantee it fires on every exit path — including a gevent GreenletExit
            # (BaseException, not caught by `except Exception`) that kills this thread
            # after the subprocess returns. Otherwise the server lock leaks forever.
            callback_sent = False
            try:
                result = script_executor.execute_script(script_name, parameters, trigger=trigger, environment=environment, task_id=task_id, script_identity_override=identity_override or None, versions=versions, device_info=device_info, virtual_script_id=virtual_script_id, team_id=team_id)
                print(f"[@route:host_script:_execute_script] CALLBACK SEND: Script completed, sending callback")

                # Send callback to server. Drop large fields the server never reads —
                # report/logs are already in R2 and discoverable via script_results,
                # so a fat stdout/stderr only risks a 413 from the proxy.
                slim_result = {k: v for k, v in (result or {}).items() if k not in ('stdout', 'stderr')}
                import requests
                callback_payload = {
                    'task_id': task_id,
                    'result': slim_result,
                }

                response = requests.post(
                    callback_url, json=callback_payload,
                    headers=server_auth_headers(), timeout=30,
                )
                callback_sent = True  # reached the server; lock release happens server-side
                if response.ok:
                    print(f"[@route:host_script:_execute_script] Callback sent successfully (status={response.status_code})")
                else:
                    body_preview = (response.text or '')[:500]
                    print(f"[@route:host_script:_execute_script] Callback FAILED: status={response.status_code} body={body_preview}")

            except Exception as e:
                print(f"[@route:host_script:_execute_script] Error in async execution: {e}")
                # Send error callback
                error_payload = {
                    'task_id': task_id,
                    'error': str(e)
                }
                try:
                    import requests
                    err_response = requests.post(
                        callback_url, json=error_payload,
                        headers=server_auth_headers(), timeout=30,
                    )
                    callback_sent = True
                    if not err_response.ok:
                        print(f"[@route:host_script:_execute_script] Error callback FAILED: status={err_response.status_code}")
                except Exception as cb_err:
                    print(f"[@route:host_script:_execute_script] Error callback exception: {cb_err}")
            finally:
                # Last-resort guarantee: if neither callback above reached the server
                # (thread killed mid-flight), send a recovery callback so the server
                # still releases the device lock and marks the task complete.
                if not callback_sent:
                    try:
                        import requests
                        requests.post(
                            callback_url,
                            json={
                                'task_id': task_id,
                                'error': 'host completion callback recovered in finally — execution thread terminated abnormally',
                            },
                            headers=server_auth_headers(),
                            timeout=30,
                        )
                        print(f"[@route:host_script:_execute_script] Recovery callback sent for task {task_id}")
                    except Exception as recover_err:
                        print(f"[@route:host_script:_execute_script] Recovery callback failed for task {task_id}: {recover_err}")

        # Start async execution
        threading.Thread(target=execute_async, daemon=True).start()
        
        return jsonify({
            'success': True,
            'message': 'Script execution started',
            'task_id': task_id
        }), 202
    else:
        # Synchronous execution (fallback)
        print(f"[@route:host_script:_execute_script] SYNC: Direct execution (no callback)")
        result = script_executor.execute_script(script_name, parameters, trigger=trigger, environment=environment, script_identity_override=identity_override or None, versions=versions, device_info=device_info, virtual_script_id=virtual_script_id, team_id=team_id)

        print(f"[@route:host_script:_execute_script] Script completed - exit_code: {result.get('exit_code')}")
        print(f"[@route:host_script:_execute_script] Script has report_url: {bool(result.get('report_url'))}")
        print(f"[@route:host_script:_execute_script] Result keys: {list(result.keys()) if result else 'None'}")
        
        return jsonify(result)
    
@host_script_bp.route('/script/get_edge_options', methods=['POST'])
@route_exception_handler()
def get_edge_options():
    data = request.get_json()
    userinterface_name = data.get('userinterface_name')
    team_id = data.get('team_id')
    ui_mode = data.get('ui_mode', 'dev') or 'dev'

    if not all([userinterface_name, team_id]):
        return jsonify({
            'success': False,
            'error': 'userinterface_name and team_id are required'
        }), 400

    print(f"[@host_script:get_edge_options] Loading edges for {userinterface_name} (mode={ui_mode})")
    
    # Import required modules
    from shared.src.lib.database.userinterface_db import get_userinterface_by_name
    from shared.src.lib.database.navigation_trees_db import get_root_tree_for_interface
    from backend_host.src.services.navigation.navigation_pathfinding import find_optimal_edge_validation_sequence
    from shared.src.lib.utils.navigation_cache import get_cached_unified_graph, populate_unified_cache
    
    # Get interface and tree ID
    interface_info = get_userinterface_by_name(userinterface_name, team_id, mode=ui_mode)
    if not interface_info:
        return jsonify({
            'success': False,
            'error': f"Interface '{userinterface_name}' not found (mode={ui_mode})"
        }), 404
    
    root_tree_info = get_root_tree_for_interface(interface_info['id'], team_id)
    if not root_tree_info:
        return jsonify({
            'success': False,
            'error': f"No root tree found for interface '{userinterface_name}'"
        }), 404
    
    tree_id = root_tree_info['id']
    
    # Check if unified cache exists, if not populate it
    cached_graph = get_cached_unified_graph(tree_id, team_id)
    if not cached_graph:
        print(f"[@host_script:get_edge_options] Cache miss - loading and populating cache")
        # Load navigation tree to populate cache
        from shared.src.lib.database.navigation_trees_db import get_full_tree, get_complete_tree_hierarchy
        tree_data = get_full_tree(tree_id, team_id)
        
        if not tree_data['success']:
            return jsonify({
                'success': False,
                'error': f"Failed to load tree: {tree_data.get('error')}"
            }), 500
        
        # Get complete hierarchy
        hierarchy_result = get_complete_tree_hierarchy(tree_id, team_id)
        if not hierarchy_result['success']:
            return jsonify({
                'success': False,
                'error': f"Failed to load hierarchy: {hierarchy_result.get('error')}"
            }), 500
        
        # Populate cache
        from shared.src.lib.utils.navigation_cache import populate_unified_cache
        cached_graph = populate_unified_cache(tree_id, team_id, hierarchy_result['hierarchy'])
        
        if not cached_graph:
            return jsonify({
                'success': False,
                'error': 'Failed to populate unified cache'
            }), 500
        
        print(f"[@host_script:get_edge_options] Cache populated: {len(cached_graph.nodes)} nodes, {len(cached_graph.edges)} edges")
    else:
        print(f"[@host_script:get_edge_options] Using cached graph: {len(cached_graph.nodes)} nodes, {len(cached_graph.edges)} edges")
    
    # Get edges from validation sequence
    edges = find_optimal_edge_validation_sequence(tree_id, team_id)
    
    if not edges:
        return jsonify({
            'success': False,
            'error': 'No edges found in navigation tree'
        }), 404
    
    print(f"[@host_script:get_edge_options] Found {len(edges)} edges from validation sequence")
    
    # Batch fetch all nodes to check verifications when use_verifications_for_kpi is true
    from shared.src.lib.database.navigation_trees_db import get_nodes_batch
    
    node_ids_to_fetch = set()
    for edge in edges:
        node_ids_to_fetch.add(edge.get('to_node_id'))  # Forward target
        node_ids_to_fetch.add(edge.get('from_node_id'))  # Reverse target
    
    batch_result = get_nodes_batch(tree_id, list(node_ids_to_fetch), team_id)
    if not batch_result.get('success'):
        return jsonify({
            'success': False,
            'error': f"Failed to batch fetch nodes: {batch_result.get('error')}"
        }), 500
    
    nodes_cache = batch_result['nodes']  # Dict: node_id -> node_data
    
    # Helper function to check if an action_set has KPI
    def action_set_has_kpi(action_set: dict, target_node_id: str) -> bool:
        """
        Check if action_set has KPI references (post-migration).
        
        If use_verifications_for_kpi is true, check target node's verifications.
        Otherwise, check action_set's kpi_references.
        """
        if not action_set:
            return False
        
        use_verifications_for_kpi = action_set.get('use_verifications_for_kpi', False)
        if use_verifications_for_kpi:
            # Check target NODE's verifications
            node_data = nodes_cache.get(target_node_id)
            if not node_data:
                return False
            verifications = node_data.get('verifications', [])
            return bool(verifications)
        else:
            # Check action_set's kpi_references
            kpi_references = action_set.get('kpi_references', [])
            return bool(kpi_references)
    
    # Extract action_set labels (bidirectional support) - FILTER by KPI availability
    # Use set to deduplicate (same edge can appear multiple times in validation sequence)
    seen_labels = set()
    edge_options = []
    edge_details = []  # For debugging/display
    filtered_count = 0
    
    for edge in edges:
        edge_data = edge.get('original_edge_data', {})
        action_sets = edge_data.get('action_sets', [])
        from_label = edge.get('from_node_label', 'unknown')
        to_label = edge.get('to_node_label', 'unknown')
        from_node_id = edge.get('from_node_id')
        to_node_id = edge.get('to_node_id')
        
        # Forward action set (index 0) - target is to_node
        if len(action_sets) > 0:
            forward_set = action_sets[0]
            forward_label = forward_set.get('label', '')
            forward_has_kpi = action_set_has_kpi(forward_set, to_node_id)
            
            if forward_label and forward_set.get('actions') and forward_has_kpi:
                if forward_label not in seen_labels:
                    seen_labels.add(forward_label)
                    edge_options.append(forward_label)
                    edge_details.append({
                        'label': forward_label,
                        'direction': 'forward',
                        'from': from_label,
                        'to': to_label
                    })
            elif forward_label and forward_set.get('actions') and not forward_has_kpi:
                filtered_count += 1
        
        # Reverse action set (index 1) - target is from_node (swapped)
        if len(action_sets) > 1:
            reverse_set = action_sets[1]
            reverse_label = reverse_set.get('label', '')
            reverse_has_kpi = action_set_has_kpi(reverse_set, from_node_id)
            
            if reverse_label and reverse_set.get('actions') and reverse_has_kpi:
                if reverse_label not in seen_labels:
                    seen_labels.add(reverse_label)
                    edge_options.append(reverse_label)
                    edge_details.append({
                        'label': reverse_label,
                        'direction': 'reverse',
                        'from': to_label,  # Swapped for reverse
                        'to': from_label   # Swapped for reverse
                    })
            elif reverse_label and reverse_set.get('actions') and not reverse_has_kpi:
                filtered_count += 1
    
    print(f"[@host_script:get_edge_options] Extracted {len(edge_options)} unique action_set labels with KPI (filtered {filtered_count} without KPI)")
    
    return jsonify({
        'success': True,
        'edge_options': edge_options,
        'edge_details': edge_details,  # For debugging/tooltips
        'count': len(edge_options),
        'cache_used': cached_graph is not None
    })
    
@host_script_bp.route('/script/upload', methods=['POST'])
@route_exception_handler()
def upload_script():
    """Receive a Python test script from the server and write it to test_scripts/.

    The server saves an uploaded script then fans it out to every host as JSON
    {filename, content, overwrite} so the script is runnable everywhere. Auth is
    enforced by the global X-API-Key check on all /host/* routes.
    """
    import os
    from werkzeug.utils import secure_filename
    from shared.src.lib.utils.script_identity_utils import get_project_root

    data = request.get_json(silent=True) or {}
    filename = (data.get('filename') or '').strip()
    content = data.get('content')
    overwrite = bool(data.get('overwrite'))

    # Re-sanitize the filename — never trust a path coming over the wire
    safe_name = secure_filename(filename)
    if not safe_name or not safe_name.endswith('.py'):
        return jsonify({'success': False, 'error': 'filename must be a .py file'}), 400
    if content is None:
        return jsonify({'success': False, 'error': 'content is required'}), 400

    scripts_dir = os.path.join(get_project_root(), 'test_scripts')
    os.makedirs(scripts_dir, exist_ok=True)
    target_path = os.path.join(scripts_dir, safe_name)

    if os.path.exists(target_path) and not overwrite:
        return jsonify({'success': False, 'exists': True, 'filename': safe_name}), 409

    with open(target_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return jsonify({'success': True, 'filename': safe_name, 'path': target_path})


@host_script_bp.route('/script/abort', methods=['POST'])
@route_exception_handler()
def abort_script():
    data = request.get_json() or {}
    device_id = data.get('device_id')

    if not device_id:
        return jsonify({
            'success': False,
            'error': 'device_id is required'
        }), 400

    from shared.src.lib.executors.script_executor import abort_running_script
    result = abort_running_script(device_id)

    status_code = 200 if result.get('success') else 500
    return jsonify(result), status_code
