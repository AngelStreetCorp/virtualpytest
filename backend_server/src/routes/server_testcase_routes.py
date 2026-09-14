"""
Server TestCase Routes - TestCase operations

This module handles test case CRUD operations using the database layer.
Execution is proxied to hosts.
"""

import uuid
from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_any_permission, require_permission
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
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
        'caller_user': incoming_trigger.get('caller_user') or user_id,
    }
    data['execution_metadata'] = execution_metadata

    query_params = {'team_id': team_id}

    response_data, status_code = proxy_to_host_with_params(
        '/host/testcase/execute', 'POST', data, query_params
    )
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
    
    query_params = {'team_id': team_id}
    
    response_data, status_code = proxy_to_host_with_params(
        f'/host/testcase/{testcase_id}/execute', 'POST', data, query_params
    )
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
        'caller_user': incoming_trigger.get('caller_user') or user_id,
    }
    data['execution_metadata'] = execution_metadata

    query_params = {'team_id': team_id}

    response_data, status_code = proxy_to_host_with_params(
        '/host/testcase/execute-from-prompt', 'POST', data, query_params
    )
    return jsonify(response_data), status_code


@server_testcase_bp.route('/generate-with-ai', methods=['POST'])
@require_permission('ai_agent:use')
@handle_route_exceptions('testcase:generate_with_ai')
def generate_with_ai():
    """
    Generate test case graph from natural language prompt (for TestCase Builder)
    
    Uses the unified execute-from-prompt endpoint but with save=false
    Returns graph + analysis for frontend to save later with user input
    
    Request body:
        {
            "prompt": "Go to live TV and verify audio",
            "userinterface_name": "example_mobile",
            "device_id": "device1"  // Optional - uses default if not provided
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
    
    # Use unified execute-from-prompt endpoint to generate plan
    # save=false means it only generates, doesn't execute or save
    generate_response, generate_status = proxy_to_host_with_params(
        '/host/testcase/execute-from-prompt', 'POST', 
        {
            'prompt': prompt,
            'userinterface_name': userinterface_name,
            'device_id': device_id,
            'host_name': 'default',  # Not used for generation-only
            'save': False,  # Don't save or execute
            'use_cache': False,  # Always generate fresh for testcase builder
            'async_execution': False  # Synchronous
        }, 
        {'team_id': team_id}
    )
    
    if not generate_response.get('success'):
        return jsonify({
            'success': False,
            'error': generate_response.get('error', 'Failed to generate plan')
        }), generate_status
    
    result = generate_response.get('result', {})
    graph = result.get('graph')
    analysis = result.get('analysis', '')
    
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
    
