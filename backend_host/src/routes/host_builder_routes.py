"""
Host Builder Routes - Standard Blocks API (Async)

All block execution is async and emits execution lifecycle events.
"""

import time
import threading
import uuid
from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event
from backend_host.src.builder.block_registry import get_available_blocks
from backend_host.src.orchestrator import ExecutionOrchestrator

# Create blueprint
host_builder_bp = Blueprint('host_builder', __name__, url_prefix='/host/builder')


@route_exception_handler()
def _execute_blocks_thread(device, execution_id, blocks):
    print(f"[@route:host_builder:_execute_blocks_thread] Starting execution: {execution_id}")
    
    # Update status to running
    with device.standard_block_executor._lock:
        device.standard_block_executor._executions[execution_id]['status'] = 'running'
        device.standard_block_executor._executions[execution_id]['message'] = 'Executing blocks...'
    
    try:
        # Execute blocks through orchestrator (logs + screenshots)
        # Note: ExecutionOrchestrator.execute_blocks is async, but internally it calls
        # device.standard_block_executor.execute_blocks which is sync (for standard blocks)
        import asyncio
        result = asyncio.run(ExecutionOrchestrator.execute_blocks(
            device=device,
            blocks=blocks,
            context=None
        ))
        
        # Update execution state with result
        with device.standard_block_executor._lock:
            device.standard_block_executor._executions[execution_id]['status'] = 'completed'
            device.standard_block_executor._executions[execution_id]['result'] = result
            device.standard_block_executor._executions[execution_id]['progress'] = 100
            device.standard_block_executor._executions[execution_id]['message'] = result.get('message', 'Completed')
        emit_execution_event(
            'builder',
            execution_id,
            'completed',
            device_id=getattr(device, 'device_id', None),
            result=result,
            progress=100,
            message=result.get('message', 'Block execution completed') if isinstance(result, dict) else 'Block execution completed',
        )
        
        print(f"[@route:host_builder:_execute_blocks_thread] Execution completed: {execution_id}")
    except Exception as exc:
        with device.standard_block_executor._lock:
            if execution_id in device.standard_block_executor._executions:
                device.standard_block_executor._executions[execution_id]['status'] = 'error'
                device.standard_block_executor._executions[execution_id]['error'] = str(exc)
                device.standard_block_executor._executions[execution_id]['progress'] = 100
                device.standard_block_executor._executions[execution_id]['message'] = f'Execution failed: {exc}'
        emit_execution_event(
            'builder',
            execution_id,
            'error',
            device_id=getattr(device, 'device_id', None),
            error=str(exc),
            progress=100,
            message='Block execution failed',
        )
        raise
    
@host_builder_bp.route('/blocks', methods=['GET', 'OPTIONS'])
def get_blocks():
    """
    Get all available standard blocks with their parameter schemas.
    
    Frontend uses this to render input fields dynamically.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        from flask import current_app
        response = current_app.response_class()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    try:
        print(f"[@route:host_builder:get_blocks] Fetching available standard blocks")
        
        # Get all blocks from registry (auto-discovers from blocks/ folder)
        blocks = get_available_blocks()
        
        print(f"[@route:host_builder:get_blocks] Found {len(blocks)} blocks")
        
        response = jsonify({
            'success': True,
            'blocks': blocks
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
        
    except Exception as e:
        print(f"[@route:host_builder:get_blocks] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        response = jsonify({
            'success': False,
            'error': f'Failed to fetch blocks: {str(e)}'
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500


@host_builder_bp.route('/execute', methods=['POST', 'OPTIONS'])
def execute_standard_block():
    """
    Execute a standard block asynchronously - returns execution_id immediately
    
    Request body:
        {
            "command": "sleep",
            "params": {"duration": 2.0},
            "device_id": "device1",
            "team_id": "team1"
        }
    
    Returns:
        {
            "success": true,
            "execution_id": "...",
            "message": "Block execution started"
        }
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = current_app.response_class()
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response
    
    try:
        data = request.get_json() or {}
        command = data.get('command')
        params = data.get('params', {})
        device_id = data.get('device_id', 'device1')
        team_id = data.get('team_id')
        
        print(f"[@route:host_builder:execute] Executing standard block: {command}")
        print(f"[@route:host_builder:execute] Params: {params}")
        print(f"[@route:host_builder:execute] Device: {device_id}")
        
        # Validate
        if not command:
            return jsonify({
                'success': False,
                'error': 'command is required'
            }), 400
        
        # Get device from app context
        host_devices = getattr(current_app, 'host_devices', {})
        if device_id not in host_devices:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} not found'
            }), 404
        
        device = host_devices[device_id]
        
        # Check if device has standard_block_executor
        if not hasattr(device, 'standard_block_executor') or not device.standard_block_executor:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} does not have StandardBlockExecutor initialized'
            }), 500
        
        # Always execute asynchronously to prevent HTTP timeouts
        # Generate execution ID
        execution_id = str(uuid.uuid4())
        
        # Store execution state
        if not hasattr(device.standard_block_executor, '_executions'):
            device.standard_block_executor._executions = {}
            device.standard_block_executor._lock = threading.Lock()
        
        with device.standard_block_executor._lock:
            device.standard_block_executor._executions[execution_id] = {
                'execution_id': execution_id,
                'status': 'running',
                'result': None,
                'error': None,
                'start_time': time.time(),
                'progress': 0,
                'message': 'Block execution starting...'
            }
        
        # Build blocks array (single block)
        blocks = [{
            'command': command,
            'params': params
        }]
        
        # Start execution in background thread
        thread = threading.Thread(
            target=_execute_blocks_thread,
            args=(device, execution_id, blocks),
            daemon=True
        )
        thread.start()
        
        print(f"[@route:host_builder:execute] Async execution started: {execution_id}")
        emit_execution_event(
            'builder',
            execution_id,
            'running',
            device_id=device_id,
            team_id=team_id,
            progress=0,
            message='Block execution started',
        )
        
        response = jsonify({
            'success': True,
            'execution_id': execution_id,
            'message': 'Block execution started'
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
        
    except Exception as e:
        print(f"[@route:host_builder:execute] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        
        response = jsonify({
            'success': False,
            'error': f'Block execution error: {str(e)}'
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500


@host_builder_bp.route('/execution/<execution_id>/status', methods=['GET'])
@route_exception_handler()
def block_execution_status(execution_id):
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
    
    # Check if device has standard_block_executor
    if not hasattr(device, 'standard_block_executor') or not device.standard_block_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have StandardBlockExecutor initialized'
        }), 500
    
    # Get execution status
    if not hasattr(device.standard_block_executor, '_executions'):
        return jsonify({
            'success': False,
            'error': f'Execution {execution_id} not found'
        }), 404
    
    with device.standard_block_executor._lock:
        if execution_id not in device.standard_block_executor._executions:
            return jsonify({
                'success': False,
                'error': f'Execution {execution_id} not found'
            }), 404
        
        execution = device.standard_block_executor._executions[execution_id].copy()
    
    # Calculate elapsed time
    elapsed_time_ms = int((time.time() - execution['start_time']) * 1000)
    
    return jsonify({
        'success': True,
        'execution_id': execution['execution_id'],
        'status': execution['status'],
        'result': execution.get('result'),
        'error': execution.get('error'),
        'progress': execution.get('progress', 0),
        'message': execution.get('message', ''),
        'elapsed_time_ms': elapsed_time_ms
    })
    
