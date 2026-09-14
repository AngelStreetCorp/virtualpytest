"""
Host Verification Routes

This module contains the host-side verification API endpoints that:
- List available verification references
- Provide status information for verification system
"""

import os
import json
import time
import threading
from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event

# Create blueprint
host_verification_bp = Blueprint('host_verification', __name__, url_prefix='/host/verification')

# =====================================================
# HOST-SIDE VERIFICATION ENDPOINTS
# =====================================================

@host_verification_bp.route('/getStatus', methods=['GET'])
@route_exception_handler()
def verification_status():
    # Get device_id from query params (defaults to device1)
    device_id = request.args.get('device_id', 'device1')
    
    print(f"[@route:verification_status] Getting verification system status for device: {device_id}")
    
    # Get device info
    device = get_device_by_id(device_id)
    if not device:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} not found'
        }), 404
    
    # Check available controllers for this device
    available_controllers = []
    
    # Check AV controller
    av_controller = get_controller(device_id, 'av')
    if av_controller:
        available_controllers.append('av')
    
    # Check remote controller
    remote_controller = get_controller(device_id, 'remote')
    if remote_controller:
        available_controllers.append('remote')
    
    # Check verification controllers
    for verification_type in ['verification_image', 'verification_text', 'verification_adb']:
        controller = get_controller(device_id, verification_type)
        if controller:
            available_controllers.append(verification_type)
    
    print(f"[@route:verification_status] Available controllers for device {device_id}: {available_controllers}")
    
    return jsonify({
        'success': True,
        'status': 'ready',
        'controllers_available': available_controllers,
        'message': 'Verification system is ready',
        'host_connected': True,
        'device_id': device_id,
        'device_model': device.device_model,
        'device_name': device.device_name
    })
    
@host_verification_bp.route('/executeBatch', methods=['POST'])
@route_exception_handler()
def verification_execute_batch():
    print("[@route:host_verification:verification_execute_batch] Starting batch verification execution")
    
    # Get request data
    data = request.get_json() or {}
    verifications = data.get('verifications', [])
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    image_source_url = data.get('image_source_url')
    tree_id = data.get('tree_id')
    node_id = data.get('node_id')
    # Interactive Editor runs flag is_test=true so node_metrics aggregates
    # exclude the row. Plumbed via navigation_context for the recorder.
    is_test = bool(data.get('is_test', False))
    # Manual verifications also generate a SUCCESS report (HTML + PNG evidence)
    # so passing checks can be reviewed for false positives. On by default for
    # this user-triggered route — the automated goto/KPI paths never set it.
    generate_success_report = bool(data.get('generate_success_report', True))

    # Extract userinterface_name (MANDATORY for reference resolution) — from verifications[0] for a
    # normal batch, or top-level for a localize-only run (which sends an empty verifications list).
    userinterface_name = (verifications[0].get('userinterface_name') if verifications else None) or data.get('userinterface_name')

    # Localize-only run: the node-edit "Verify" button sends an EMPTY list + a node_id to ask "is the
    # device on THIS node?". Answer via the node's stored FINGERPRINT (the match_fingerprint image
    # verification) instead of 400-ing for lack of a hand-authored reference — so fingerprint-only nodes
    # (live screens, dispatch tabs) become verifiable. No fingerprint -> falls through to the 400 below.
    if not verifications and node_id and tree_id and team_id:
        try:
            from shared.src.lib.utils.navigation_cache import get_cached_unified_graph
            _ug = get_cached_unified_graph(tree_id, team_id)
            _node = _ug.nodes.get(node_id) if (_ug is not None and node_id in _ug.nodes) else None
            _fp = (_node.get('__fingerprint') if _node else None) or {}
            if _fp.get('dhash'):
                verifications = [{'verification_type': 'image', 'command': 'match_fingerprint',
                                  'params': {'fingerprint': _fp, 'threshold': 14},
                                  'userinterface_name': userinterface_name}]
                print(f"[@route:host_verification:verification_execute_batch] localize-only run -> fingerprint verify for node {node_id}")
        except Exception as _e:
            print(f"[@route:host_verification:verification_execute_batch] fingerprint fallback failed: {_e}")

    print(f"[@route:host_verification:verification_execute_batch] Processing {len(verifications)} verifications for device: {device_id}, team: {team_id}, userinterface: {userinterface_name}")
    
    # Validate
    if not verifications:
        return jsonify({'success': False, 'error': 'verifications are required'}), 400
    
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
    
    # Check if device has verification_executor
    if not hasattr(device, 'verification_executor') or not device.verification_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have VerificationExecutor initialized'
        }), 500
    
    # Two dispatch paths share this single route, mirroring host_actions_routes:
    #
    # - **Node verification (Run button)**: when `tree_id` and `node_id` are
    #   both set, dispatch to `NavigationExecutor.execute_single_node_verification`.
    #   That path writes one node_metrics row through the same single-owner
    #   recorder used by goto's per-step loop.
    # - **Ad-hoc verifications (MCP, raw verification calls)**: when either
    #   field is missing, fall through to `VerificationExecutor.execute_verifications`
    #   directly. No DB write — there is no node to attribute the result to.
    is_node_verification = bool(tree_id and node_id)

    if is_node_verification and (not hasattr(device, 'navigation_executor') or not device.navigation_executor):
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have NavigationExecutor initialized'
        }), 500

    # Stamp is_test on navigation_context so execute_single_node_verification's
    # record_node_execution call picks it up.
    if not hasattr(device, 'navigation_context') or device.navigation_context is None:
        device.navigation_context = {}
    device.navigation_context['is_test'] = is_test

    # Always execute asynchronously to prevent HTTP timeouts
    # Playwright will run sync INSIDE the thread (no cross-thread issues)
    print(f"[@route:host_verification:verification_execute_batch] Executing asynchronously with threading (is_node_verification={is_node_verification})")

    # Generate execution ID
    import uuid
    execution_id = str(uuid.uuid4())

    # Store execution state
    if not hasattr(device.verification_executor, '_executions'):
        device.verification_executor._executions = {}
        device.verification_executor._lock = threading.Lock()

    with device.verification_executor._lock:
        device.verification_executor._executions[execution_id] = {
            'execution_id': execution_id,
            'status': 'running',
            'result': None,
            'error': None,
            'start_time': time.time(),
            'progress': 0,
            'message': 'Verification execution starting...'
        }

    # Start execution in background thread
    thread = threading.Thread(
        target=_execute_verifications_thread,
        args=(device, execution_id, verifications, userinterface_name, image_source_url, team_id, tree_id, node_id, is_node_verification, generate_success_report),
        daemon=True
    )
    thread.start()
    
    print(f"[@route:host_verification:verification_execute_batch] Async execution started: {execution_id}")
    emit_execution_event(
        'verification',
        execution_id,
        'running',
        device_id=device_id,
        team_id=team_id,
        progress=0,
        message='Verification execution started',
    )
    
    return jsonify({
        'success': True,
        'execution_id': execution_id,
        'message': 'Verification execution started'
    })
    
@host_verification_bp.route('/execution/<execution_id>/status', methods=['GET'])
@route_exception_handler()
def verification_execution_status(execution_id):
    # Prefer WebWorker status (web batches)
    try:
        from backend_host.src.lib.web_worker import WebWorker
        worker_status = WebWorker.instance().get_status(execution_id)
    except Exception:
        worker_status = None
    if worker_status:
        return jsonify({
            'success': True,
            'execution_id': worker_status['execution_id'],
            'status': worker_status['status'],
            'result': worker_status.get('result'),
            'error': worker_status.get('error'),
            'progress': worker_status.get('progress', 0),
            'message': worker_status.get('message', ''),
            'elapsed_time_ms': worker_status.get('elapsed_time_ms', 0)
        })

    # Fallback to legacy executor store (non-web batches)
    device_id = request.args.get('device_id', 'device1')
    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found in host'}), 404
    device = host_devices[device_id]
    if not hasattr(device, 'verification_executor') or not device.verification_executor:
        return jsonify({'success': False, 'error': f'Device {device_id} does not have VerificationExecutor initialized'}), 500
    status = device.verification_executor.get_execution_status(execution_id)
    return jsonify(status)
    
# ========================================
# BACKGROUND EXECUTION THREAD
# ========================================

def _execute_verifications_thread(
    device,
    execution_id: str,
    verifications: list,
    userinterface_name: str,
    image_source_url: str,
    team_id: str,
    tree_id: str,
    node_id: str,
    is_node_verification: bool = False,
    generate_success_report: bool = False,
):
    """Execute verifications in background thread with progress tracking"""
    import sys
    import io
    import time
    
    # Capture logs for verification execution
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
        with device.verification_executor._lock:
            device.verification_executor._executions[execution_id]['message'] = 'Executing verifications...'
            device.verification_executor._executions[execution_id]['progress'] = 50
        
        # Execute verifications via orchestrator (includes logging + screenshots)
        from backend_host.src.orchestrator import ExecutionOrchestrator
        import asyncio
        if is_node_verification:
            result = asyncio.run(ExecutionOrchestrator.execute_single_node_verification(
                device=device,
                tree_id=tree_id,
                node_id=node_id,
                verifications=verifications,
                userinterface_name=userinterface_name,
                image_source_url=image_source_url,
                team_id=team_id,
                generate_success_report=generate_success_report,
            ))
        else:
            result = asyncio.run(ExecutionOrchestrator.execute_verifications(
                device=device,
                verifications=verifications,
                userinterface_name=userinterface_name,
                image_source_url=image_source_url,
                team_id=team_id,
                tree_id=tree_id,
                node_id=node_id,
                generate_success_report=generate_success_report
            ))
        
        # Stop log capture (orchestrator already captured logs in result['logs'])
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        # Note: logs already in result from orchestrator, no need to add again
        
        # Update with result
        with device.verification_executor._lock:
            if result.get('success'):
                device.verification_executor._executions[execution_id]['status'] = 'completed'
                device.verification_executor._executions[execution_id]['result'] = result
                device.verification_executor._executions[execution_id]['progress'] = 100
                device.verification_executor._executions[execution_id]['message'] = 'Verification execution completed'
                emit_execution_event(
                    'verification',
                    execution_id,
                    'completed',
                    device_id=getattr(device, 'device_id', None),
                    team_id=team_id,
                    result=result,
                    progress=100,
                    message='Verification execution completed',
                )
            else:
                device.verification_executor._executions[execution_id]['status'] = 'error'
                device.verification_executor._executions[execution_id]['error'] = result.get('error', 'Verification execution failed')
                device.verification_executor._executions[execution_id]['result'] = result
                device.verification_executor._executions[execution_id]['progress'] = 100
                device.verification_executor._executions[execution_id]['message'] = 'Verification execution failed'
                emit_execution_event(
                    'verification',
                    execution_id,
                    'error',
                    device_id=getattr(device, 'device_id', None),
                    team_id=team_id,
                    result=result,
                    error=result.get('error', 'Verification execution failed'),
                    progress=100,
                    message='Verification execution failed',
                )
    
    except Exception as e:
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
        # Update with error
        with device.verification_executor._lock:
            device.verification_executor._executions[execution_id]['status'] = 'error'
            device.verification_executor._executions[execution_id]['error'] = str(e)
            device.verification_executor._executions[execution_id]['progress'] = 100
            device.verification_executor._executions[execution_id]['message'] = f'Verification execution error: {str(e)}'
        emit_execution_event(
            'verification',
            execution_id,
            'error',
            device_id=getattr(device, 'device_id', None),
            team_id=team_id,
            error=str(e),
            progress=100,
            message='Verification execution error',
        )
    finally:
        # Always restore stdout/stderr
        if sys.stdout != old_stdout:
            sys.stdout = old_stdout
        if sys.stderr != old_stderr:
            sys.stderr = old_stderr
