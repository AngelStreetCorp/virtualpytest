"""
Server TestCase Routes - TestCase operations

This module handles test case CRUD operations using the database layer.
Execution is proxied to hosts.
"""

import threading
import uuid
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_any_permission, require_permission
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from backend_server.src.lib.utils.trigger_utils import resolve_caller_user
from backend_server.src.lib.utils.lock_utils import (
    acquire_device_lock,
    clear_device_active_script,
    get_client_ip,
    get_device_lock_info,
    release_device_lock,
)
from backend_server.src.routes.server_control_routes import _build_lock_conflict_payload
from backend_server.src.routes.server_system_socket_routes import emit_system_update
from backend_server.src.routes.server_executable_routes import invalidate_executable_list_cache
from shared.src.lib.database.testcase_db import (
    create_testcase,
    update_testcase,
    get_testcase,
    delete_testcase,
    list_testcases,
    get_testcase_by_name,
    get_next_version_number,
    get_testcase_versions,
    restore_testcase_version,
    validate_testcase_graph,
)
from shared.src.lib.database.folder_tag_db import (
    list_all_folders,
    list_all_tags
)
from shared.src.lib.database.library_visibility_db import list_hidden_library_keys

server_testcase_bp = Blueprint('server_testcase', __name__, url_prefix='/server/testcase')

# Device locks held by async /execute runs, keyed by host execution_id, released by
# the host's terminal execution event (/server/executionEvent). A run whose terminal
# event lands while its dispatch is still in flight goes to _finished_executions so the
# registration releases at once; the set is only kept while a dispatch is in flight.
_testcase_locks = {}
_finished_executions = set()
_dispatches_in_flight = 0
_testcase_locks_guard = threading.Lock()


def _release_testcase_lock(lock):
    """Release the lock one /execute run took, or, when it ran under its user's Take
    Control, only clear the run's annotation: that control was the caller's, not ours."""
    host_name, device_id, job_id = lock['host_name'], lock['device_id'], lock['job_id']
    if lock['subordinate']:
        result = clear_device_active_script(host_name=host_name, device_id=device_id, owner_job_id=job_id)
        if result.get('cleared'):
            emit_system_update('lock_changed', {
                'host_name': host_name,
                'device_id': device_id,
                'is_locked': True,
                'lock_info': result.get('lock_info'),
            })
        return
    result = release_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='testcase_execution',
        owner_job_id=job_id,
    )
    if result.get('released'):
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
            'lock_info': result.get('lock_info'),
        })
        print(f"[@server_testcase:lock] Released {host_name}:{device_id} (job {job_id})")


def release_testcase_execution_lock(execution_id):
    """Called on a testcase's terminal execution event."""
    with _testcase_locks_guard:
        lock = _testcase_locks.pop(execution_id, None)
        if lock is None:
            if _dispatches_in_flight:
                _finished_executions.add(execution_id)
            return
    _release_testcase_lock(lock)


def acquire_testcase_lock(data, user_id, client_ip, run_name):
    """Take Control for a testcase run unless the caller already holds it.

    Under the caller's own manual_control (same user, or same session) the run goes
    subordinate and that lock stays; a free device is locked as testcase_execution and
    released when the run ends. Returns (lock, None) or (None, refusal response).
    """
    host_name = data['host_name']
    device_id = data['device_id']
    job_id = str(uuid.uuid4())
    lock_result = acquire_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='testcase_execution',
        owner_session_id=data.get('session_id') or job_id,
        owner_user_id=user_id or getattr(request, 'user_id', None),
        owner_user_name=data.get('user_name'),
        owner_job_id=job_id,
        lock_reason=f"testcase_execute:{run_name}",
        can_force_takeover=True,
        client_ip=client_ip,
        allow_same_user_takeover=True,
    )
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)
        if conflict:
            return None, (jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423)
        return None, (jsonify({
            'success': False,
            'error': f'Failed to lock device {host_name}:{device_id} for testcase execution',
        }), 500)
    lock = {
        'host_name': host_name,
        'device_id': device_id,
        'job_id': job_id,
        'subordinate': bool(lock_result.get('subordinate')),
    }
    if not lock['subordinate']:
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': True,
            'lock_info': lock_result.get('lock_info'),
        })
    return lock, None


def dispatch_testcase_under_lock(lock, endpoint, data, query_params, *, track_async, timeout=30):
    """Proxy a testcase run to the host and release its lock when the run is over.

    With track_async, a started async run (execution_id returned) keeps the lock until
    its terminal testcase event; anything else is over when the host answers.
    """
    global _dispatches_in_flight
    with _testcase_locks_guard:
        _dispatches_in_flight += 1
    response_data, status_code = None, 500
    try:
        response_data, status_code = proxy_to_host_with_params(
            endpoint, 'POST', data, query_params, timeout=timeout
        )
    finally:
        execution_id = response_data.get('execution_id') if isinstance(response_data, dict) else None
        started = (track_async and status_code < 400 and execution_id
                   and response_data.get('success', True))
        with _testcase_locks_guard:
            finished = bool(execution_id) and execution_id in _finished_executions
            if started and not finished:
                _testcase_locks[execution_id] = lock
            _dispatches_in_flight -= 1
            if not _dispatches_in_flight:
                _finished_executions.clear()
        if not started or finished:
            _release_testcase_lock(lock)
    return response_data, status_code


@server_testcase_bp.route('/save', methods=['POST'])
@require_any_permission('testcases:create', 'testcases:edit')
@handle_route_exceptions('testcase:testcase_save')
def testcase_save():
    """Save or update test case definition"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Check if updating existing testcase
    testcase_id = data.get('testcase_id')
    
    if testcase_id:
        # Update existing testcase
        success = update_testcase(
            testcase_id=testcase_id,
            graph_json=data.get('graph_json'),
            description=data.get('description'),
            userinterface_name=data.get('userinterface_name'),
            team_id=team_id,
            folder=data.get('folder'),  # NEW: Folder name
            tags=data.get('tags'),  # NEW: List of tag names
            testcase_name=data.get('testcase_name')  # NEW: Support renaming
        )
        
        if success:
            invalidate_executable_list_cache()
            # Fetch updated testcase
            testcase = get_testcase(testcase_id, team_id)
            if testcase:
                return jsonify({'success': True, 'testcase': testcase})
            else:
                return jsonify({'success': False, 'error': 'Test case not found after update'}), 404
        else:
            return jsonify({'success': False, 'error': 'Failed to update test case'}), 500
    else:
        # Create new testcase
        testcase_name = data.get('testcase_name')
        if not testcase_name:
            return jsonify({'success': False, 'error': 'testcase_name is required'}), 400
        
        graph_json = data.get('graph_json')
        if not graph_json:
            return jsonify({'success': False, 'error': 'graph_json is required'}), 400
        
        overwrite = data.get('overwrite', False)  # Allow overwriting existing test case
        
        new_testcase_result = create_testcase(
            team_id=team_id,
            testcase_name=testcase_name,
            graph_json=graph_json,
            description=data.get('description'),
            userinterface_name=data.get('userinterface_name'),
            created_by=data.get('created_by'),
            creation_method=data.get('creation_method', 'visual'),
            ai_prompt=data.get('ai_prompt'),
            ai_analysis=data.get('ai_analysis'),
            overwrite=overwrite,
            folder=data.get('folder'),  # NEW: Folder name (user-selected or typed)
            tags=data.get('tags'),  # NEW: List of tag names
            available_nodes=data.get('available_nodes')  # NEW: Nodes from AI generation
        )
        
        # Handle dict response (new format with auto-increment info)
        if isinstance(new_testcase_result, dict) and new_testcase_result.get('success'):
            testcase_id = new_testcase_result['testcase_id']
            final_name = new_testcase_result['testcase_name']
            
            # Fetch full testcase data
            testcase = get_testcase(testcase_id, team_id)
            if testcase:
                invalidate_executable_list_cache()
                return jsonify({
                    'success': True, 
                    'testcase': testcase,
                    'testcase_id': testcase_id,
                    'testcase_name': final_name,
                    'action': 'created'
                })
            else:
                return jsonify({'success': False, 'error': 'Test case not found after creation'}), 404
        elif new_testcase_result == 'VALIDATION_FAILED':
            return jsonify({'success': False, 'error': 'Graph validation failed. Check graph structure and userinterface name.'}), 400
        elif new_testcase_result == 'DUPLICATE_NAME':
            return jsonify({'success': False, 'error': f'Test case name "{testcase_name}" already exists. Please choose a different name or enable overwrite.'}), 409
        elif new_testcase_result:
            # Old format (backward compatibility) - just testcase_id string
            testcase = get_testcase(new_testcase_result, team_id)
            if testcase:
                return jsonify({'success': True, 'testcase': testcase, 'action': 'updated' if overwrite else 'created'})
            else:
                return jsonify({'success': False, 'error': 'Test case not found after creation'}), 404
        else:
            return jsonify({'success': False, 'error': 'Failed to create test case'}), 500
        
@server_testcase_bp.route('/list', methods=['GET'])
@handle_route_exceptions('testcase:testcase_list')
def testcase_list():
    """
    List all test cases for a team
    
    Query params:
        - team_id: Required
        - include_inactive: Optional (default: false)
        - include_graph: Optional (default: false) - Include graph_json field (slower)
    """
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
    include_graph = request.args.get('include_graph', 'false').lower() == 'true'
    include_hidden = request.args.get('include_hidden', 'false').lower() == 'true'
    
    testcases = list_testcases(team_id, include_inactive=include_inactive, include_graph=include_graph)
    if not include_hidden:
        hidden_testcase_ids = list_hidden_library_keys(team_id, 'testcase')
        testcases = [
            testcase for testcase in testcases
            if testcase.get('testcase_id') not in hidden_testcase_ids
        ]
    
    return jsonify({'success': True, 'testcases': testcases})
    
@server_testcase_bp.route('/<testcase_id>', methods=['GET'])
@handle_route_exceptions('testcase:testcase_get')
def testcase_get(testcase_id):
    """Get test case definition by ID"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    testcase = get_testcase(testcase_id, team_id)
    
    if testcase:
        return jsonify({'success': True, 'testcase': testcase})
    else:
        return jsonify({'success': False, 'error': 'Test case not found'}), 404


@server_testcase_bp.route('/<testcase_id>/versions', methods=['GET'])
@handle_route_exceptions('testcase:testcase_versions')
def testcase_versions(testcase_id):
    """Get recent testcase definition versions."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    versions = get_testcase_versions(testcase_id, team_id, limit=10)
    if not versions:
        return jsonify({'success': False, 'error': 'Test case not found'}), 404
    return jsonify({'success': True, 'versions': versions})


@server_testcase_bp.route('/<testcase_id>/restore/<int:version_number>', methods=['POST'])
@require_permission('testcases:edit')
@handle_route_exceptions('testcase:testcase_restore_version')
def testcase_restore_version(testcase_id, version_number):
    """Restore a testcase definition version as the new latest version."""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    versions = get_testcase_versions(testcase_id, team_id, limit=100)
    target_version = next((version for version in versions if version.get('version_number') == version_number), None)
    if not target_version:
        return jsonify({'success': False, 'error': f'Version {version_number} not found'}), 404

    validation_result = validate_testcase_graph(
        target_version.get('graph_json'),
        target_version.get('userinterface_name'),
        team_id,
    )
    if not validation_result.get('success'):
        return jsonify({
            'success': False,
            'error': 'Validation failed: ' + ', '.join(validation_result.get('errors', [])),
        }), 400

    result = restore_testcase_version(testcase_id, version_number, team_id)
    if result.get('success'):
        invalidate_executable_list_cache()
        return jsonify(result)
    return jsonify({'success': False, 'error': result.get('error', 'Failed to restore test case')}), 500
        
@server_testcase_bp.route('/<testcase_id>', methods=['DELETE'])
@require_permission('testcases:delete')
@handle_route_exceptions('testcase:testcase_delete')
def testcase_delete(testcase_id):
    """Delete test case"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    print(f"[@server_testcase:delete] Attempting to delete testcase_id={testcase_id}, team_id={team_id}")
    success = delete_testcase(testcase_id, team_id)
    
    if success:
        invalidate_executable_list_cache()
        print(f"[@server_testcase:delete] Successfully deleted testcase: {testcase_id}")
        return jsonify({'success': True, 'message': 'Test case deleted'})
    else:
        print(f"[@server_testcase:delete] Failed to delete - testcase not found: {testcase_id}")
        return jsonify({'success': False, 'error': 'Test case not found or already deleted'}), 404
        
@server_testcase_bp.route('/execute', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testcase:testcase_execute_direct')
def testcase_execute_direct():
    """Execute test case directly from graph (no save required) - supports async execution"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Validate required fields
    if 'graph_json' not in data:
        return jsonify({'success': False, 'error': 'graph_json is required'}), 400
    if 'device_id' not in data:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    if 'host_name' not in data:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    
    # async_execution defaults to True on the host side to prevent timeouts
    # Frontend can override by passing async_execution: false

    # Trigger provenance: where did this request come from? Stored in execution_metadata
    # so testcase_executor can attach it to the ScriptExecutionContext at execution start.
    try:
        from backend_server.src.lib.utils.lock_utils import get_client_ip
        client_ip = get_client_ip()
    except Exception:
        client_ip = request.headers.get('X-Forwarded-For') or request.remote_addr or None
    user_id = data.get('user_id') or request.headers.get('X-User-ID')
    execution_metadata = data.get('execution_metadata') if isinstance(data.get('execution_metadata'), dict) else {}
    incoming_trigger = execution_metadata.get('trigger') if isinstance(execution_metadata.get('trigger'), dict) else {}
    execution_metadata['trigger'] = {
        'type': incoming_trigger.get('type') or 'api',
        'caller_ip': incoming_trigger.get('caller_ip') or client_ip,
        'caller_user': incoming_trigger.get('caller_user') or resolve_caller_user(user_id, data.get('user_name')),
    }
    data['execution_metadata'] = execution_metadata

    lock, refusal = acquire_testcase_lock(
        data, user_id, client_ip, data.get('testcase_name') or 'unsaved_testcase')
    if refusal:
        return refusal
    response_data, status_code = dispatch_testcase_under_lock(
        lock, '/host/testcase/execute', data, {'team_id': team_id}, track_async=True)
    return jsonify(response_data), status_code


@server_testcase_bp.route('/execution/<execution_id>/status', methods=['GET'])
@handle_route_exceptions('testcase:testcase_execution_status')
def testcase_execution_status(execution_id):
    """Get status of async test case execution"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    query_params = {'team_id': team_id}
    
    response_data, status_code = proxy_to_host_with_params(
        f'/host/testcase/execution/{execution_id}/status', 'GET', None, query_params
    )
    return jsonify(response_data), status_code


@server_testcase_bp.route('/abortRunning', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testcase:testcase_abort_running')
def testcase_abort_running():
    """Abort currently running async testcase execution on a host device."""
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    host_name = data.get('host_name')
    device_id = data.get('device_id')
    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'host_name and device_id required'}), 400

    query_params = {'team_id': team_id}
    response_data, status_code = proxy_to_host_with_params(
        '/host/testcase/abortRunning', 'POST', data, query_params
    )
    return jsonify(response_data), status_code


@server_testcase_bp.route('/<testcase_id>/execute', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testcase:testcase_execute')
def testcase_execute(testcase_id):
    """Execute test case by ID"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    if not data.get('host_name') or not data.get('device_id'):
        return jsonify({'success': False, 'error': 'host_name and device_id are required'}), 400

    # The host runs this synchronously: the lock is held for the call.
    lock, refusal = acquire_testcase_lock(
        data, data.get('user_id') or request.headers.get('X-User-ID'), get_client_ip(), testcase_id)
    if refusal:
        return refusal
    response_data, status_code = dispatch_testcase_under_lock(
        lock, f'/host/testcase/{testcase_id}/execute', data, {'team_id': team_id}, track_async=False)
    return jsonify(response_data), status_code


@server_testcase_bp.route('/<testcase_id>/next-version', methods=['GET'])
@handle_route_exceptions('testcase:testcase_get_next_version')
def testcase_get_next_version(testcase_id):
    """Get next version number for a test case"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    next_version = get_next_version_number(testcase_id, team_id)
    
    return jsonify({'success': True, 'next_version': next_version})
        
@server_testcase_bp.route('/<testcase_id>/history', methods=['GET'])
@handle_route_exceptions('testcase:testcase_history')
def testcase_history(testcase_id):
    """Get execution history for a test case"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    limit = request.args.get('limit', '50')
    query_params = {'team_id': team_id, 'limit': limit}
    
    response_data, status_code = proxy_to_host_with_params(
        f'/host/testcase/{testcase_id}/history', 'GET', None, query_params
    )
    return jsonify(response_data), status_code


@server_testcase_bp.route('/execute-from-prompt', methods=['POST'])
@require_permission('execution.run:run_test')
@handle_route_exceptions('testcase:execute_from_prompt')
def execute_from_prompt():
    """
    Unified AI execution endpoint - proxies to host
    
    This replaces the old /server/ai/executePrompt route.
    Supports optional save flag for both:
    - Live AI Modal: save=false (ephemeral)
    - TestCase Builder: save=true (persistent)
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400

    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    # Trigger provenance: AI-prompt-generated runs are tagged `type=ai` so Grafana
    # can distinguish them from regular API-driven runs.
    try:
        from backend_server.src.lib.utils.lock_utils import get_client_ip
        client_ip = get_client_ip()
    except Exception:
        client_ip = request.headers.get('X-Forwarded-For') or request.remote_addr or None
    user_id = data.get('user_id') or request.headers.get('X-User-ID')
    execution_metadata = data.get('execution_metadata') if isinstance(data.get('execution_metadata'), dict) else {}
    incoming_trigger = execution_metadata.get('trigger') if isinstance(execution_metadata.get('trigger'), dict) else {}
    execution_metadata['trigger'] = {
        'type': incoming_trigger.get('type') or 'ai',
        'caller_ip': incoming_trigger.get('caller_ip') or client_ip,
        'caller_user': incoming_trigger.get('caller_user') or resolve_caller_user(user_id, data.get('user_name')),
    }
    data['execution_metadata'] = execution_metadata

    if not data.get('host_name') or not data.get('device_id'):
        return jsonify({'success': False, 'error': 'host_name and device_id are required'}), 400

    # The host generates the graph (an LLM call) before it starts the run, hence the
    # longer timeout; an async run then holds the lock until its terminal testcase event.
    lock, refusal = acquire_testcase_lock(data, user_id, client_ip, 'ai_prompt')
    if refusal:
        return refusal
    response_data, status_code = dispatch_testcase_under_lock(
        lock, '/host/testcase/execute-from-prompt', data, {'team_id': team_id},
        track_async=True, timeout=180)
    return jsonify(response_data), status_code


@server_testcase_bp.route('/generate-with-ai', methods=['POST'])
@require_permission('ai_agent:use')
@handle_route_exceptions('testcase:generate_with_ai')
def generate_with_ai():
    """
    Generate test case graph from natural language prompt (for TestCase Builder)
    
    Uses the host's AIGraphBuilder (/host/ai/generatePlan): generates only, never runs
    Returns graph + analysis for frontend to save later with user input
    
    Request body:
        {
            "prompt": "Go to live TV and verify audio",
            "userinterface_name": "example_mobile",
            "device_id": "device1",  // Optional - uses default if not provided
            "host_name": "host1"     // Host whose AIGraphBuilder generates the graph
        }
    
    Response:
        {
            "success": true,
            "graph": {nodes: [...], edges: [...]},
            "analysis": "Goal: ...\nThinking: ...",
            "testcase_name": "AI: Go to live TV",
            "ai_prompt": "Go to live TV and verify audio"
        }
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
    
    prompt = data.get('prompt')
    userinterface_name = data.get('userinterface_name')
    device_id = data.get('device_id', 'device1')  # Default to device1
    
    if not prompt:
        return jsonify({'success': False, 'error': 'prompt is required'}), 400
    
    if not userinterface_name:
        return jsonify({'success': False, 'error': 'userinterface_name is required'}), 400
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Generation only: nothing runs on the device, so no lock.
    generate_response, generate_status = proxy_to_host_with_params(
        '/host/ai/generatePlan', 'POST',
        {
            'prompt': prompt,
            'userinterface_name': userinterface_name,
            'device_id': device_id,
            'host_name': data.get('host_name'),
        },
        {'team_id': team_id},
        timeout=180,
    )

    if not generate_response.get('success'):
        return jsonify({
            'success': False,
            'error': generate_response.get('error', 'Failed to generate plan')
        }), generate_status if generate_status >= 400 else 400

    graph = generate_response.get('graph')
    analysis = generate_response.get('analysis', '')

    if not graph:
        return jsonify({
            'success': False,
            'error': 'No graph generated by AI'
        }), 500

    # Generate suggested name from prompt
    testcase_name = f"AI: {prompt[:50]}" if len(prompt) > 50 else f"AI: {prompt}"
    
    # Return the graph directly from AI (already has nodes/edges in React Flow format)
    return jsonify({
        'success': True,
        'graph': graph,  # Use AI-generated graph directly
        'testcase_name': testcase_name,
        'description': analysis,  # Use AI analysis as description
        'ai_prompt': prompt,
        'ai_analysis': analysis
    }), 200
    
@server_testcase_bp.route('/folders-tags', methods=['GET'])
@handle_route_exceptions('testcase:get_folders_and_tags')
def get_folders_and_tags():
    """
    Get all folders and tags for dropdown selection.
    Used by TestCaseBuilder save dialog and RunTests selector.
    
    Returns:
        {
            "success": true,
            "folders": [{folder_id, name}, ...],
            "tags": [{tag_id, name, color}, ...]
        }
    """
    folders = list_all_folders()
    tags = list_all_tags()
    
    return jsonify({
        'success': True,
        'folders': folders,
        'tags': tags
    })
    
