"""
Host Action Routes - Device Action Execution (Async)

All action execution (ADB, web, etc.) uses simple background threading and returns execution_id immediately for polling.
"""

import time
import threading
import uuid
from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.orchestrator import ExecutionOrchestrator
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event

# Create blueprint
host_actions_bp = Blueprint('host_actions', __name__, url_prefix='/host/action')


@host_actions_bp.route('/executeBatch', methods=['POST'])
@route_exception_handler('Action execution batch error: {e}')
def action_execute_batch():
    """Execute a batch of actions on a device.

    Two dispatch paths share this single route:

    - **Edge step (Run button / goto single-step)**: when `tree_id`,
      `edge_id`, `action_set_id`, and `target_node_id` are all set, we
      dispatch to `NavigationExecutor.execute_single_edge_step`. That path
      is identical to one step of goto: records execution_results with
      variant + wall-clock duration, runs the destination verification,
      queues KPI, updates position pointer.
    - **Ad-hoc actions (MCP press_key, raw remote test, etc.)**: when any
      of the four edge fields is missing, we dispatch to
      `ActionExecutor.execute_actions` directly. No DB write — there is no
      edge to attribute the result to.
    """
    print("[@route:host_actions:action_execute_batch] Starting action execution", flush=True)

    # Get request data
    data = request.get_json() or {}
    actions = data.get('actions', [])
    retry_actions = data.get('retry_actions', [])
    failure_actions = data.get('failure_actions', [])
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')
    # Forwarded so verification-as-action steps with a reference_name resolve
    # against the right interface (and not against device.device_model).
    userinterface_name = data.get('userinterface_name')

    tree_id = data.get('tree_id')
    edge_id = data.get('edge_id')
    action_set_id = data.get('action_set_id')
    target_node_id = data.get('target_node_id')
    current_node_id = data.get('current_node_id')

    # Run scope: variant name or composition (list / '+'-joined) or None for
    # base; canonicalized. See docs/agent/navigation/VARIANT.md "Composition".
    from shared.src.lib.utils.navigation_graph import canonical_variant_name
    variant = canonical_variant_name(data.get('variant'))

    # Interactive Editor runs (Run / Goto / Edge Run) set is_test=true so the
    # metrics trigger excludes them from edge_metrics. CLI / pipeline runs
    # default to false. The flag is plumbed via device.navigation_context so
    # NavigationExecutor's per-step recording stamps it on every row.
    is_test = bool(data.get('is_test', False))

    # Per-edge settle delay (ms). Forwarded into the step dict so
    # NavigationExecutor honors the same final_wait_time as a goto step.
    try:
        final_wait_time = int(data.get('final_wait_time') or 0)
    except (TypeError, ValueError):
        final_wait_time = 0
    if final_wait_time < 0:
        final_wait_time = 0

    print(f"[@route:host_actions:action_execute_batch] Processing {len(actions)} command(s) for device: {device_id}, team: {team_id}", flush=True)

    # Validate
    if not actions:
        return jsonify({'success': False, 'error': 'actions are required'}), 400
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    # Get host device registry from app context
    host_devices = getattr(current_app, 'host_devices', {})
    if device_id not in host_devices:
        return jsonify({'success': False, 'error': f'Device {device_id} not found in host'}), 404

    device = host_devices[device_id]

    # Stamp the run scope on the device's navigation_context so the
    # NavigationExecutor's per-step recording stamps the same variant.
    if not hasattr(device, 'navigation_context') or device.navigation_context is None:
        device.navigation_context = {}
    device.navigation_context['variant'] = variant
    device.navigation_context['is_test'] = is_test

    is_edge_step = bool(tree_id and edge_id and action_set_id and target_node_id)

    if is_edge_step:
        if not hasattr(device, 'navigation_executor') or not device.navigation_executor:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} does not have NavigationExecutor initialized'
            }), 500
    else:
        if not hasattr(device, 'action_executor') or not device.action_executor:
            return jsonify({
                'success': False,
                'error': f'Device {device_id} does not have ActionExecutor initialized'
            }), 500

    from backend_host.src.lib.web_worker import WebWorker
    from backend_host.src.orchestrator import ExecutionOrchestrator

    async def run_fn():
        try:
            if is_edge_step:
                result = await ExecutionOrchestrator.execute_single_edge_step(
                    device=device,
                    tree_id=tree_id,
                    userinterface_name=userinterface_name,
                    edge_id=edge_id,
                    action_set_id=action_set_id,
                    target_node_id=target_node_id,
                    actions=actions,
                    retry_actions=retry_actions,
                    failure_actions=failure_actions,
                    current_node_id=current_node_id,
                    team_id=team_id,
                    final_wait_time=final_wait_time,
                )
            else:
                result = await ExecutionOrchestrator.execute_actions(
                    device=device,
                    actions=actions,
                    retry_actions=retry_actions,
                    failure_actions=failure_actions,
                    team_id=team_id,
                    context=None,
                    userinterface_name=userinterface_name,
                )
            emit_execution_event(
                'action',
                execution_id,
                'completed',
                device_id=device_id,
                team_id=team_id,
                result=result,
                progress=100,
                message=result.get('message') if isinstance(result, dict) else None,
            )
            return result
        except Exception as exc:
            emit_execution_event(
                'action',
                execution_id,
                'error',
                device_id=device_id,
                team_id=team_id,
                error=str(exc),
                progress=100,
                message='Action execution failed',
            )
            raise

    payload = {
        'tree_id': tree_id,
        'edge_id': edge_id,
        'action_set_id': action_set_id,
        'target_node_id': target_node_id,
        'is_edge_step': is_edge_step,
        'action_count': len(actions),
        'device_id': device_id,
        'team_id': team_id,
    }

    execution_id = WebWorker.instance().submit_async('action', payload, run_fn)
    print(f"[@route:host_actions:action_execute_batch] Async execution started: {execution_id} (edge_step={is_edge_step})", flush=True)
    emit_execution_event(
        'action',
        execution_id,
        'running',
        device_id=device_id,
        team_id=team_id,
        progress=0,
        message='Action execution started',
    )
    return jsonify({'success': True, 'execution_id': execution_id, 'message': 'Action execution started'})


@host_actions_bp.route('/execution/<execution_id>/status', methods=['GET'])
@route_exception_handler('Execution status error: {e}')
def action_execution_status(execution_id):
    """Get status of async action execution"""
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
    
    # Check if device has action_executor
    if not hasattr(device, 'action_executor') or not device.action_executor:
        return jsonify({
            'success': False,
            'error': f'Device {device_id} does not have ActionExecutor initialized'
        }), 500
    
    # Get execution status
    if not hasattr(device.action_executor, '_executions'):
        return jsonify({
            'success': False,
            'error': f'Execution {execution_id} not found'
        }), 404
    
    with device.action_executor._lock:
        if execution_id not in device.action_executor._executions:
            return jsonify({
                'success': False,
                'error': f'Execution {execution_id} not found'
            }), 404
        
        execution = device.action_executor._executions[execution_id].copy()
    
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


@host_actions_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for host action service"""
    return jsonify({
        'success': True,
        'message': 'Host action service is running'
    })


@host_actions_bp.route('/abortExecution', methods=['POST'])
@route_exception_handler('Abort action execution error: {e}')
def abort_action_execution():
    """Abort an async action execution."""
    data = request.get_json() or {}
    execution_id = data.get('execution_id')
    device_id = data.get('device_id', 'device1')
    team_id = request.args.get('team_id')

    if not execution_id:
        return jsonify({'success': False, 'error': 'execution_id is required'}), 400

    from backend_host.src.lib.web_worker import WebWorker

    result = WebWorker.instance().cancel_execution(execution_id=execution_id, device_id=device_id)
    if not result.get('success'):
        return jsonify(result), 404

    if result.get('aborted'):
        emit_execution_event(
            'action',
            execution_id,
            'aborted',
            device_id=device_id,
            team_id=team_id,
            progress=100,
            message='Action execution aborted by user',
        )

    return jsonify(result), 200
