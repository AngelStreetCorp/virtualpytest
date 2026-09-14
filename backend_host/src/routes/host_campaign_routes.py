"""
Host Campaign Routes - Execute campaigns on host using device script executors

This module receives campaign execution requests from the server and executes them
at the host level where scripts can properly access devices and infrastructure.
"""

from flask import Blueprint, request, jsonify, current_app
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event
import threading
import time
import requests
from typing import Dict, Any

# Import campaign executor (moved to shared level)
from shared.src.lib.executors.campaign_executor import CampaignExecutor

# Create blueprint
host_campaign_bp = Blueprint('host_campaign', __name__, url_prefix='/host/campaigns')

# Global dictionary to track running campaigns on this host
running_campaigns = {}
active_campaign_executors = {}

@route_exception_handler()
def execute_campaign_async(campaign_config: Dict[str, Any], execution_id: str, callback_url: str = None, executor: CampaignExecutor = None):
    print(f"[@route:host_campaign] Starting async campaign execution: {execution_id}")
    try:
        executor = executor or CampaignExecutor()
        result = executor.execute_campaign(campaign_config)
        
        print(f"[@route:host_campaign] Campaign {execution_id} completed with success: {result.get('success')}")
        
        # Update running campaigns status
        if execution_id in running_campaigns:
            if result.get('aborted'):
                final_status = 'aborted'
            else:
                final_status = 'completed' if result.get('success') else 'failed'
            running_campaigns[execution_id].update({
                'status': final_status,
                'result': result,
                'completed_at': time.time()
            })
    except Exception as exc:
        if execution_id in running_campaigns:
            running_campaigns[execution_id].update({
                'status': 'failed',
                'error': str(exc),
                'completed_at': time.time()
            })
        raise
    
    # Send callback to server if provided
    if callback_url:
        try:
            if result.get('aborted'):
                final_status = 'aborted'
            else:
                final_status = 'completed' if result.get('success') else 'failed'
            callback_data = {
                'execution_id': execution_id,
                'status': final_status,
                'campaign_id': campaign_config.get('campaign_id'),
                'host_name': campaign_config.get('host') or campaign_config.get('host_name'),
                'device_id': campaign_config.get('device') or campaign_config.get('device_id'),
                'team_id': campaign_config.get('team_id'),
                'result': result,
                'error': None if final_status == 'completed' else result.get('error'),
                'completed_at': time.time(),
                'external_callback_url': campaign_config.get('external_callback_url'),
                'callback_on_script_complete': campaign_config.get('callback_on_script_complete', False),
                'callback_on_campaign_complete': campaign_config.get('callback_on_campaign_complete', True),
                'lock_owner_session_id': campaign_config.get('lock_owner_session_id'),
                'lock_owner_job_id': campaign_config.get('lock_owner_job_id'),
                'deployment_execution_id': campaign_config.get('deployment_execution_id'),
            }
            
            print(f"[@route:host_campaign] Sending callback to server: {callback_url}")
            response = requests.post(callback_url, json=callback_data, timeout=30)
            
            if response.status_code == 200:
                print(f"[@route:host_campaign] Callback sent successfully")
            else:
                print(f"[@route:host_campaign] Callback failed with status: {response.status_code}")
                
        except Exception as e:
            print(f"[@route:host_campaign] Error sending callback: {e}")
    active_campaign_executors.pop(execution_id, None)
    
# =====================================================
# HOST CAMPAIGN EXECUTION ENDPOINTS
# =====================================================

@host_campaign_bp.route('/execute', methods=['POST'])
@route_exception_handler()
def execute_campaign():
    print(f"[@route:host_campaign:execute_campaign] Received campaign execution request")
    
    # Get request data
    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'Request body is required'
        }), 400
    
    # Validate required fields
    required_fields = ['campaign_id', 'name', 'script_configurations']
    for field in required_fields:
        if field not in data:
            return jsonify({
                'success': False,
                'error': f'Missing required field: {field}'
            }), 400
    
    # Validate script configurations
    script_configs = data.get('script_configurations', [])
    if not script_configs:
        return jsonify({
            'success': False,
            'error': 'At least one script configuration is required'
        }), 400
    
    for i, script_config in enumerate(script_configs):
        if 'script_name' not in script_config:
            return jsonify({
                'success': False,
                'error': f'script_name is required for script configuration {i+1}'
            }), 400
    
    # Generate execution ID
    campaign_id = data['campaign_id']
    execution_id = f"{campaign_id}_{int(time.time())}"
    
    # Get callback URL and task_id from request
    callback_url = data.get('callback_url')
    task_id = data.get('task_id')
    
    print(f"[@route:host_campaign:execute_campaign] Campaign: {campaign_id}")
    print(f"[@route:host_campaign:execute_campaign] Execution ID: {execution_id}")
    print(f"[@route:host_campaign:execute_campaign] Scripts: {len(script_configs)}")
    print(f"[@route:host_campaign:execute_campaign] Callback URL: {callback_url}")
    print(f"[@route:host_campaign:execute_campaign] Task ID: {task_id}")
    
    # Prepare campaign config for host execution
    campaign_config = data.copy()
    
    # Remove server-specific fields that shouldn't be passed to campaign executor
    server_fields = ['callback_url', 'task_id', 'async']
    for field in server_fields:
        campaign_config.pop(field, None)
    
    # Determine execution mode
    async_execution = data.get('async', True)
    
    if async_execution:
        executor = CampaignExecutor()
        # Execute asynchronously
        running_campaigns[execution_id] = {
            'campaign_id': campaign_id,
            'execution_id': execution_id,
            'status': 'running',
            'started_at': time.time(),
            'campaign_config': campaign_config,
            'task_id': task_id,
            'device_id': campaign_config.get('device_id') or campaign_config.get('device'),
        }
        active_campaign_executors[execution_id] = executor
        
        # Start campaign execution in background thread
        thread = threading.Thread(
            target=execute_campaign_async,
            args=(campaign_config, execution_id, callback_url, executor)
        )
        thread.daemon = True
        thread.start()
        
        print(f"[@route:host_campaign:execute_campaign] Started async execution")
        emit_execution_event(
            'campaign',
            execution_id,
            'running',
            team_id=campaign_config.get('team_id'),
            progress=0,
            message='Campaign execution started',
        )
        
        return jsonify({
            'success': True,
            'message': 'Campaign execution started on host',
            'execution_id': execution_id,
            'campaign_id': campaign_id,
            'async': True,
            'status': 'running'
        }), 202
    
    else:
        # Execute synchronously
        print(f"[@route:host_campaign:execute_campaign] Starting sync execution")
        
        executor = CampaignExecutor()
        result = executor.execute_campaign(campaign_config)
        
        print(f"[@route:host_campaign:execute_campaign] Sync execution completed")
        
        return jsonify({
            'success': True,
            'message': 'Campaign execution completed on host',
            'campaign_id': campaign_id,
            'async': False,
            'result': result
        }), 200


@host_campaign_bp.route('/abortRunning', methods=['POST'])
@route_exception_handler()
def abort_running_campaign():
    """Abort running campaign orchestrator and currently active script for a device."""
    data = request.get_json() or {}
    device_id = data.get('device_id')
    execution_id = data.get('execution_id')
    reason = data.get('reason', 'Aborted by user')

    if not device_id and not execution_id:
        return jsonify({'success': False, 'error': 'device_id or execution_id is required'}), 400

    aborted: Dict[str, Any] = {}
    for exec_id, campaign_info in list(running_campaigns.items()):
        if campaign_info.get('status') != 'running':
            continue
        if execution_id and exec_id != execution_id:
            continue
        if device_id and campaign_info.get('device_id') != device_id:
            continue

        executor = active_campaign_executors.get(exec_id)
        if executor:
            aborted[exec_id] = executor.request_abort(device_id=campaign_info.get('device_id') or device_id, reason=reason)
        else:
            aborted[exec_id] = {'success': False, 'error': 'No active executor found'}

        running_campaigns[exec_id]['status'] = 'aborted'
        running_campaigns[exec_id]['error'] = reason
        running_campaigns[exec_id]['completed_at'] = time.time()
        emit_execution_event(
            'campaign',
            exec_id,
            'aborted',
            team_id=campaign_info.get('campaign_config', {}).get('team_id'),
            host_name=campaign_info.get('campaign_config', {}).get('host_name') or campaign_info.get('campaign_config', {}).get('host'),
            device_id=campaign_info.get('device_id'),
            error=reason,
            progress=100,
            message='Campaign execution aborted by user',
        )

    if not aborted:
        return jsonify({
            'success': True,
            'aborted': False,
            'message': 'No running campaign matched the abort criteria',
        }), 200

    return jsonify({
        'success': True,
        'aborted': True,
        'aborted_campaigns': aborted,
        'count': len(aborted),
    }), 200
        
@host_campaign_bp.route('/status/<execution_id>', methods=['GET'])
@route_exception_handler()
def get_campaign_execution_status(execution_id: str):
    print(f"[@route:host_campaign:get_campaign_execution_status] Checking status for: {execution_id}")
    
    if execution_id not in running_campaigns:
        return jsonify({
            'success': False,
            'error': 'Campaign execution not found on this host'
        }), 404
    
    campaign_info = running_campaigns[execution_id]
    
    # Calculate runtime
    start_time = campaign_info.get('started_at', time.time())
    current_time = time.time()
    runtime_seconds = int(current_time - start_time)
    
    response_data = {
        'success': True,
        'execution_id': execution_id,
        'campaign_id': campaign_info['campaign_id'],
        'status': campaign_info['status'],
        'runtime_seconds': runtime_seconds,
        'host': True  # Indicate this is from host
    }
    
    # Add result if completed
    if campaign_info['status'] in ['completed', 'failed']:
        if 'result' in campaign_info:
            response_data['result'] = campaign_info['result']
        if 'error' in campaign_info:
            response_data['error'] = campaign_info['error']
        if 'completed_at' in campaign_info:
            total_time = int(campaign_info['completed_at'] - start_time)
            response_data['total_time_seconds'] = total_time
    
    return jsonify(response_data), 200
    
@host_campaign_bp.route('/running', methods=['GET'])
@route_exception_handler()
def get_running_campaigns():
    print(f"[@route:host_campaign:get_running_campaigns] Listing running campaigns")
    
    # Filter out completed campaigns older than 1 hour
    current_time = time.time()
    hour_ago = current_time - 3600
    
    active_campaigns = {}
    for execution_id, campaign_info in running_campaigns.items():
        # Keep running campaigns and recently completed ones
        if (campaign_info['status'] == 'running' or 
            (campaign_info.get('completed_at', current_time) > hour_ago)):
            
            # Calculate runtime
            start_time = campaign_info.get('started_at', current_time)
            runtime_seconds = int(current_time - start_time)
            
            active_campaigns[execution_id] = {
                'execution_id': execution_id,
                'campaign_id': campaign_info['campaign_id'],
                'status': campaign_info['status'],
                'started_at': campaign_info['started_at'],
                'runtime_seconds': runtime_seconds,
                'host': True  # Indicate this is from host
            }
            
            if campaign_info['status'] in ['completed', 'failed']:
                if 'completed_at' in campaign_info:
                    total_time = int(campaign_info['completed_at'] - start_time)
                    active_campaigns[execution_id]['total_time_seconds'] = total_time
    
    return jsonify({
        'success': True,
        'running_campaigns': list(active_campaigns.values()),
        'count': len(active_campaigns),
        'host': True  # Indicate this is from host
    }), 200
    
