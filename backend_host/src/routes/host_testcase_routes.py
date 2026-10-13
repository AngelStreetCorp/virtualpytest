"""
Host TestCase Routes - TestCase Builder execution on host

This module handles direct test case execution on the host device.
Test cases are visual no-code scripts created in TestCase Builder.
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler

# Create blueprint
host_testcase_bp = Blueprint('host_testcase', __name__, url_prefix='/host/testcase')


@host_testcase_bp.route('/save', methods=['POST'])
@route_exception_handler()
def testcase_save():
    from shared.src.lib.database.testcase_db import create_testcase, update_testcase, get_testcase_by_name
    
    print("[@host_testcase] Saving test case definition")
    
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    
    testcase_name = data.get('testcase_name')
    graph_json = data.get('graph_json')
    description = data.get('description')
    userinterface_name = data.get('userinterface_name')
    created_by = data.get('created_by')
    environment = data.get('environment', 'dev')
    
    # Validate
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if not testcase_name:
        return jsonify({'success': False, 'error': 'testcase_name is required'}), 400
    if not graph_json:
        return jsonify({'success': False, 'error': 'graph_json is required'}), 400
    
    # Check if test case already exists (update vs create)
    existing = get_testcase_by_name(testcase_name, team_id, environment)
    
    if existing:
        # Update existing
        success = update_testcase(
            testcase_id=existing['testcase_id'],
            graph_json=graph_json,
            description=description,
            userinterface_name=userinterface_name,
            team_id=team_id
        )
        
        if success:
            print(f"[@host_testcase] Updated test case: {testcase_name}")
            return jsonify({
                'success': True,
                'testcase_id': existing['testcase_id'],
                'action': 'updated'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to update test case'}), 500
    else:
        # Create new
        created = create_testcase(
            team_id=team_id,
            testcase_name=testcase_name,
            graph_json=graph_json,
            description=description,
            userinterface_name=userinterface_name,
            created_by=created_by,
            environment=environment
        )
        # A new row comes back as {testcase_id, testcase_name, success} (BUG-0215).
        testcase_id = created.get('testcase_id') if isinstance(created, dict) else created
        
        if testcase_id:
            print(f"[@host_testcase] Created test case: {testcase_name} (ID: {testcase_id})")
            return jsonify({
                'success': True,
                'testcase_id': testcase_id,
                'action': 'created'
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to create test case'}), 500
    
@host_testcase_bp.route('/list', methods=['GET'])
@route_exception_handler()
def testcase_list():
    from shared.src.lib.database.testcase_db import list_testcases
    
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    include_graph = request.args.get('include_graph', 'false').lower() == 'true'
    
    testcases = list_testcases(team_id, include_graph=include_graph)
    
    return jsonify({
        'success': True,
        'testcases': testcases
    })
    
@host_testcase_bp.route('/<testcase_id>', methods=['GET'])
@route_exception_handler()
def testcase_get(testcase_id):
    from shared.src.lib.database.testcase_db import get_testcase
    
    team_id = request.args.get('team_id')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    testcase = get_testcase(testcase_id, team_id)
    
    if testcase:
        return jsonify({
            'success': True,
            'testcase': testcase
        })
    else:
        return jsonify({'success': False, 'error': 'Test case not found'}), 404
    
@host_testcase_bp.route('/<testcase_id>', methods=['DELETE'])
@route_exception_handler()
def testcase_delete(testcase_id):
    from shared.src.lib.database.testcase_db import delete_testcase
    
    team_id = request.args.get('team_id')
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    success = delete_testcase(testcase_id, team_id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Test case not found or delete failed'}), 404
    
@host_testcase_bp.route('/<testcase_id>/execute', methods=['POST'])
@route_exception_handler()
def testcase_execute(testcase_id):
    from backend_host.src.services.testcase.testcase_executor import TestCaseExecutor
    from shared.src.lib.database.testcase_db import get_testcase
    
    print(f"[@host_testcase] Executing test case: {testcase_id}")
    
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    device_id = data.get('device_id', 'device1')
    # Run-time values for the testcase's scriptConfig inputs (campaign per-row
    # parameters) — stamped onto the loaded graph by the executor.
    parameters = data.get('parameters') or {}

    # Validate
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    # Get test case to extract name
    testcase = get_testcase(testcase_id, team_id)
    if not testcase:
        return jsonify({'success': False, 'error': 'Test case not found'}), 404
    
    testcase_name = testcase['testcase_name']
    
    # Get device info from registry
    if not hasattr(current_app, 'host_devices') or device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    host_name = getattr(device, 'host_name', 'unknown-host')
    device_name = device.device_name
    device_model = device.device_model
    
    # Execute test case (userinterface_name from request overrides testcase's stored UI)
    executor = TestCaseExecutor()
    result = executor.execute_testcase(
        testcase_name=testcase_name,
        team_id=team_id,
        host_name=host_name,
        device_id=device_id,
        device_name=device_name,
        device_model=device_model,
        parameters=parameters,
        userinterface_name=data.get('userinterface_name', ''),
    )
    
    print(f"[@host_testcase] Execution result: success={result.get('success')}")
    
    return jsonify(result)
    
@host_testcase_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def testcase_execute_direct():
    from backend_host.src.services.testcase.testcase_executor import TestCaseExecutor
    
    print(f"[@host_testcase] Executing test case from graph (no save)")
    
    data = request.get_json() or {}
    team_id = request.args.get('team_id')
    
    # Extract data
    graph_json = data.get('graph_json')
    device_id = data.get('device_id', 'device1')
    host_name = data.get('host_name')
    userinterface_name = data.get('userinterface_name', '')
    testcase_name = data.get('testcase_name', 'unsaved_testcase')  # 🆕 NEW: Extract testcase name
    execution_metadata = data.get('execution_metadata') or {}
    async_execution = data.get('async_execution', True)  # Default to async to prevent timeouts
    # Single-step QuickTest runs pass generate_report=False to skip the report tail
    # (video/R2/HTML/DB) — just execute the step(s) and report live results, fast.
    generate_report = data.get('generate_report', True)
    
    # Validate
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    if not graph_json:
        return jsonify({'success': False, 'error': 'graph_json is required'}), 400
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    
    print(f"[@host_testcase] Executing testcase: {testcase_name}")  # 🆕 NEW: Log testcase name
    
    # Get device info from registry
    if not hasattr(current_app, 'host_devices') or device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found'}), 404
    
    device = current_app.host_devices[device_id]
    device_name = device.device_name
    device_model = device.device_model
    
    # ✅ AUTO-INJECT device_model into scriptConfig.inputs if it exists
    # This ensures device_model_name is always populated with the correct runtime value
    if 'scriptConfig' in graph_json and 'inputs' in graph_json['scriptConfig']:
        for input_def in graph_json['scriptConfig']['inputs']:
            if input_def.get('name') == 'device_model_name':
                input_def['value'] = device_model
                print(f"[@host_testcase] Auto-injected device_model_name = {device_model}")
                break
    
    # Get or create global executor instance for async execution tracking
    if not hasattr(current_app, 'testcase_executor'):
        current_app.testcase_executor = TestCaseExecutor()
    
    executor = current_app.testcase_executor
    
    if async_execution:
        # Async execution - return immediately with execution_id
        result = executor.execute_testcase_from_graph_async(
            graph=graph_json,
            team_id=team_id,
            host_name=host_name,
            device_id=device_id,
            device_name=device_name,
            device_model=device_model,
            userinterface_name=userinterface_name,
            testcase_name=testcase_name,  # 🆕 NEW: Pass testcase name to executor
            execution_metadata=execution_metadata,
            generate_report=generate_report,
        )
        print(f"[@host_testcase] Async execution started: {result.get('execution_id')}")
    else:
        # Synchronous execution - wait for completion (may timeout for long tests)
        result = executor.execute_testcase_from_graph(
            graph=graph_json,
            team_id=team_id,
            host_name=host_name,
            device_id=device_id,
            device_name=device_name,
            device_model=device_model,
            userinterface_name=userinterface_name,
            testcase_name=testcase_name,  # 🆕 NEW: Pass testcase name to executor
            execution_metadata=execution_metadata,
            generate_report=generate_report,
        )
        print(f"[@host_testcase] Execution result: success={result.get('success')}")
    
    return jsonify(result)
    
@host_testcase_bp.route('/execution/<execution_id>/status', methods=['GET'])
@route_exception_handler()
def testcase_execution_status(execution_id):
    from backend_host.src.services.testcase.testcase_executor import TestCaseExecutor
    
    # Get global executor instance (we need a singleton pattern here)
    # For now, we'll use a module-level executor
    if not hasattr(current_app, 'testcase_executor'):
        current_app.testcase_executor = TestCaseExecutor()
    
    executor = current_app.testcase_executor
    status = executor.get_execution_status(execution_id)
    
    if status is None:
        return jsonify({'success': False, 'error': 'Execution not found'}), 404
    
    return jsonify({'success': True, 'status': status})


@host_testcase_bp.route('/abortRunning', methods=['POST'])
@route_exception_handler()
def testcase_abort_running():
    """Abort currently running async testcase execution on a device."""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    execution_id = data.get('execution_id')

    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400

    if not hasattr(current_app, 'testcase_executor'):
        return jsonify({
            'success': True,
            'aborted': False,
            'message': f'No testcase executor found for device {device_id}',
        }), 200

    executor = current_app.testcase_executor
    result = executor.abort_running_execution(device_id=device_id, execution_id=execution_id)
    return jsonify(result), 200
    
@host_testcase_bp.route('/<testcase_id>/history', methods=['GET'])
@route_exception_handler()
def testcase_history(testcase_id):
    from shared.src.lib.database.testcase_db import get_testcase, get_testcase_execution_history
    
    team_id = request.args.get('team_id')
    limit = int(request.args.get('limit', 50))
    
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    
    # Get test case to extract name
    testcase = get_testcase(testcase_id, team_id)
    if not testcase:
        return jsonify({'success': False, 'error': 'Test case not found'}), 404
    
    testcase_name = testcase['testcase_name']
    
    # Get execution history from script_results
    history = get_testcase_execution_history(testcase_name, team_id, limit)
    
    return jsonify({
        'success': True,
        'testcase_name': testcase_name,
        'history': history
    })
    
@host_testcase_bp.route('/execute-from-prompt', methods=['POST'])
@route_exception_handler()
def execute_from_prompt():
    """Generate a testcase graph from a prompt (device.ai_builder), optionally save it,
    and run it through the TestCaseExecutor exactly like /execute."""
    from shared.src.lib.database.testcase_db import create_testcase
    from backend_host.src.services.testcase.testcase_executor import TestCaseExecutor

    data = request.get_json() or {}
    team_id = request.args.get('team_id')

    prompt = data.get('prompt')
    userinterface_name = data.get('userinterface_name')
    device_id = data.get('device_id')
    host_name = data.get('host_name')
    save_testcase = data.get('save', False)
    testcase_name = data.get('testcase_name')
    execution_metadata = data.get('execution_metadata') or {}
    async_execution = data.get('async_execution', False)

    if not all([prompt, userinterface_name, device_id, host_name, team_id]):
        return jsonify({
            'success': False,
            'error': 'Missing required fields: prompt, userinterface_name, device_id, host_name, team_id'
        }), 400
    if save_testcase and not testcase_name:
        return jsonify({'success': False, 'error': 'testcase_name is required when save=true'}), 400

    if not hasattr(current_app, 'host_devices') or device_id not in current_app.host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found in host registry'}), 404
    device = current_app.host_devices[device_id]
    if not getattr(device, 'ai_builder', None):
        return jsonify({'success': False, 'error': f'Device {device_id} does not have AIGraphBuilder initialized'}), 500

    # STEP 1: prompt -> graph (preprocessing, disambiguation and cache live in the builder)
    print(f"[@host_testcase:execute_from_prompt] Generating graph: {prompt[:50]}...")
    generated = device.ai_builder.generate_graph(
        prompt=prompt,
        userinterface_name=userinterface_name,
        team_id=team_id,
        notes=data.get('notes'),
    )
    if generated.get('needs_disambiguation'):
        return jsonify({
            'success': False,
            'needs_disambiguation': True,
            'analysis': generated,
            'available_nodes': generated.get('available_nodes', []),
        }), 200  # Not an error, just needs user input
    if not generated.get('success') or not generated.get('graph'):
        return jsonify({'success': False, 'error': generated.get('error') or 'No graph generated by AI'}), 400
    graph = generated['graph']
    analysis = generated.get('analysis', '')
    # Test Prompt: the run starts at home (shared/src/lib/utils/testcase_start.py) — the gate
    # that wakes the device and launches the app; the graph saved and returned includes it.
    if data.get('start_node_label'):
        from shared.src.lib.utils.testcase_start import with_start_node
        graph = with_start_node(graph, data['start_node_label'])

    # STEP 2: optional save
    testcase_id = None
    if save_testcase:
        created = create_testcase(
            team_id=team_id,
            testcase_name=testcase_name,
            graph_json=graph,
            description=data.get('description') or analysis,
            userinterface_name=userinterface_name,
            created_by=data.get('created_by'),
            creation_method='ai',
            ai_prompt=prompt,
            ai_analysis=analysis,
        )
        # A new row comes back as {testcase_id, testcase_name, success} (BUG-0215).
        testcase_id = created.get('testcase_id') if isinstance(created, dict) else created
        if testcase_id == 'VALIDATION_FAILED':
            return jsonify({
                'success': False,
                'error': 'Test case validation failed - graph references non-existent nodes, edges, or actions. Check logs for details.'
            }), 400

    # STEP 3: run the graph
    if not hasattr(current_app, 'testcase_executor'):
        current_app.testcase_executor = TestCaseExecutor()
    executor = current_app.testcase_executor
    run_kwargs = dict(
        graph=graph,
        team_id=team_id,
        host_name=host_name,
        device_id=device_id,
        device_name=device.device_name,
        device_model=device.device_model,
        userinterface_name=userinterface_name,
        testcase_name=testcase_name or (f"AI: {prompt[:50]}"),
        execution_metadata=execution_metadata,
    )
    if async_execution:
        result = executor.execute_testcase_from_graph_async(**run_kwargs)
    else:
        result = executor.execute_testcase_from_graph(**run_kwargs)

    response = {
        **result,
        'graph': graph,
        'analysis': analysis,
        'saved': bool(testcase_id),
    }
    if testcase_id:
        response['testcase_id'] = testcase_id
    return jsonify(response)
