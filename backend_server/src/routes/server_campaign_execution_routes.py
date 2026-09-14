"""
Campaign Execution API Routes

This module contains the campaign execution endpoints for:
- Executing campaigns
- Getting campaign execution results
- Managing campaign executions
"""

import uuid
from flask import Blueprint, request, jsonify, current_app, session
from typing import Dict, Any
import time

# Import utility functions
from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_permission
from backend_server.src.lib.auth_middleware import require_permission
from backend_server.src.lib.utils.completion_notifier import notify_completion
from backend_server.src.lib.utils.webhook_utils import resolve_callback_url
from backend_server.src.lib.utils.lock_utils import (
    abort_and_force_unlock,
    acquire_device_lock,
    clear_device_active_script,
    get_client_ip,
    get_device_lock_info,
    release_device_lock,
)
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.routes.server_system_socket_routes import emit_system_update
from shared.src.lib.utils.build_url_utils import buildServerUrl, call_host
from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.adhoc_execution import create_adhoc_execution, complete_adhoc_execution

# Import database functions
from shared.src.lib.database.campaign_executions_db import (
    get_campaign_execution_with_scripts,
    get_campaign_results
)

# Create blueprint
server_campaign_execution_bp = Blueprint('server_campaign_execution', __name__, url_prefix='/server/campaigns')

# =====================================================
# CAMPAIGN EXECUTION ENDPOINTS
# =====================================================


def _build_lock_conflict_payload(host_name: str, device_id: str, lock_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'success': False,
        'error': f'Device {host_name}:{device_id} is locked',
        'errorType': 'device_locked',
        'owner_type': lock_info.get('owner_type'),
        'owner_user_id': lock_info.get('owner_user_id'),
        'owner_session_id': lock_info.get('owner_session_id'),
        'owner_job_id': lock_info.get('owner_job_id'),
        'can_wait': True,
        'can_force_takeover': bool(lock_info.get('can_force_takeover', False)),
        'message': lock_info.get('lock_reason') or 'Device is currently in use by another execution',
        'lock_info': lock_info,
    }

@server_campaign_execution_bp.route('/execution/<execution_id>/status', methods=['GET'])
def get_campaign_execution_status(execution_id: str):
    """Get status of campaign execution - proxy to host"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    query_params = {'team_id': team_id}

    response_data, status_code = proxy_to_host_with_params(
        f'/host/campaigns/status/{execution_id}', 'GET', None, query_params
    )
    return jsonify(response_data), status_code


@server_campaign_execution_bp.route('/abortRunning', methods=['POST'])
@require_permission('campaigns:execute')
@handle_route_exceptions('server_campaign_execution:abort_running')
def abort_campaign_running():
    """Abort running campaign execution on host for given device/execution."""
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400

    host_name = data.get('host_name')
    device_id = data.get('device_id')
    execution_id = data.get('execution_id')
    if not host_name:
        return jsonify({'success': False, 'error': 'host_name is required'}), 400
    if not device_id and not execution_id:
        return jsonify({'success': False, 'error': 'device_id or execution_id is required'}), 400

    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if not host_info:
        return jsonify({'success': False, 'error': f'Host not found: {host_name}'}), 404

    payload = {
        'device_id': device_id,
        'execution_id': execution_id,
        'reason': data.get('reason', 'Aborted by user'),
    }
    query_params = {'team_id': team_id}
    response_data, status_code = call_host(
        host_info,
        '/host/campaigns/abortRunning',
        method='POST',
        data=payload,
        query_params=query_params,
        timeout=30,
    )
    return jsonify(response_data), status_code


@server_campaign_execution_bp.route('/execute', methods=['POST'])
@require_permission('campaigns:execute')
@handle_route_exceptions('server_campaign_execution:execute')
def execute_campaign():
    """Execute a campaign - proxy to host and let CampaignExecutor handle everything"""
    print(f"[@server_campaign:execute_campaign] Received campaign execution request")
    # Accept team_id from query params OR body
    data = request.get_json(silent=True) or {}
    team_id = request.args.get('team_id') or data.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    data = request.get_json() or {}
    if not data:
        return jsonify({'success': False, 'error': 'Request body is required'}), 400
    required_fields = ['campaign_id', 'name', 'script_configurations']
    for field in required_fields:
        if field not in data:
            return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
    script_configs = data.get('script_configurations', [])
    if not script_configs:
        return jsonify({'success': False, 'error': 'At least one script configuration is required'}), 400
    for i, script_config in enumerate(script_configs):
        if 'script_name' not in script_config:
            return jsonify({'success': False, 'error': f'script_name is required for script configuration {i+1}'}), 400

    host_name = data.get('host_name') or data.get('host')
    device_id = data.get("device_id") or data.get("device") or data.get("device_name")
    if not host_name or not device_id:
        return jsonify({'success': False, 'error': 'host_name/host and device_id/device are required'}), 400

    requested_session_id = data.get('session_id')
    if requested_session_id:
        session['session_id'] = requested_session_id
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    owner_session_id = session['session_id']
    owner_user_id = data.get('user_id') or request.headers.get('X-User-ID')
    owner_user_name = data.get('user_name')
    owner_job_id = f"campaign:{data['campaign_id']}:{int(time.time() * 1000)}"

    host_manager = get_host_manager()
    host_info = host_manager.get_host(host_name)
    if not host_info:
        return jsonify({'success': False, 'error': f'Host not found: {host_name}'}), 404

    # Handle force_unlock: abort running execution and release existing lock
    force_unlock = bool(data.get('force_unlock', False))
    if force_unlock:
        # strict=True: a new campaign is about to start on this device.
        force_result = abort_and_force_unlock(host_name, device_id, strict=True)
        if not force_result.get('success'):
            return jsonify({
                'success': False,
                'error': force_result.get('error') or 'Failed to force unlock device',
                'errorType': force_result.get('errorType') or 'force_unlock_failed',
                'details': force_result.get('details'),
            }), 409
        emit_system_update('lock_changed', {
            'host_name': host_name,
            'device_id': device_id,
            'is_locked': False,
            'lock_info': force_result.get('lock_info'),
        })
        print(
            f"[@server_campaign:execute_campaign] Force unlocked {host_name}:{device_id} "
            f"(aborted={force_result.get('aborted')})"
        )

    lock_result = acquire_device_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type='script_execution',
        owner_session_id=owner_session_id,
        owner_user_id=owner_user_id,
        owner_user_name=owner_user_name,
        owner_job_id=owner_job_id,
        # Name, not id: the lock_reason is a display label — a bare uuid is dropped
        # by the UI and the running campaign then shows no name at all.
        lock_reason=f"campaign_execute:{data.get('name') or data['campaign_id']}",
        can_force_takeover=True,
        allow_same_user_takeover=True,
    )
    if not lock_result.get('success'):
        conflict = lock_result.get('conflict') or get_device_lock_info(host_name, device_id)
        if conflict:
            return jsonify(_build_lock_conflict_payload(host_name, device_id, conflict)), 423
        return jsonify({'success': False, 'error': 'Failed to acquire campaign execution lock'}), 500

    emit_system_update('lock_changed', {
        'host_name': host_name,
        'device_id': device_id,
        'is_locked': True,
        'lock_info': lock_result.get('lock_info'),
    })

    # Persist a running execution row so it survives page refresh
    adhoc_exec_id = None
    try:
        supabase = get_supabase_client()
        _dep, adhoc_exec = create_adhoc_execution(
            supabase,
            team_id=team_id,
            host_name=host_name,
            device_id=device_id,
            script_name=data.get('name', data['campaign_id']),
            campaign_id=data['campaign_id'],
            # Persist the resolved campaign config (post per-device
            # script_configurations overrides) so "Last Executions" can
            # rerun this campaign row without refetching after a page reload.
            rerun_payload={
                'type': 'campaign',
                'campaignName': data.get('name') or data['campaign_id'],
                'hostName': host_name,
                'deviceId': device_id,
                'campaignSource': 'db' if data.get('campaign_id') else 'file',
                'campaignConfig': data,
            },
        )
        adhoc_exec_id = adhoc_exec['id']
        emit_system_update('deployment_changed', {
            'domain': 'deployment',
            'action': 'execution_started',
            'execution_id': adhoc_exec_id,
        })
        print(f"[@server_campaign:execute_campaign] Created adhoc execution {adhoc_exec_id}")
    except Exception as adhoc_err:
        print(f"[@server_campaign:execute_campaign] Adhoc execution row failed (non-fatal): {adhoc_err}")

    campaign_config = data.copy()
    campaign_config['team_id'] = team_id
    campaign_config['host_name'] = host_name
    campaign_config['device_id'] = device_id
    if adhoc_exec_id:
        campaign_config['deployment_execution_id'] = adhoc_exec_id

    # Trigger provenance: mirror server_script_routes — trust caller's explicit
    # trigger.type if provided (MCP/scheduler proxies set it), otherwise default
    # to "api" since we're in an HTTP route. Fall back to request client IP and
    # X-User-ID so child script reports carry caller_ip/caller_user.
    incoming_trigger = data.get('trigger') if isinstance(data.get('trigger'), dict) else {}
    client_ip = get_client_ip()
    campaign_config['trigger'] = {
        'type': (incoming_trigger.get('type') or 'api'),
        'caller_ip': incoming_trigger.get('caller_ip') or client_ip,
        'caller_user': incoming_trigger.get('caller_user') or owner_user_id,
    }
    callback_url = data.get('callback_url')
    if callback_url and not resolve_callback_url(callback_url):
        release_result = release_device_lock(
            host_name=host_name,
            device_id=device_id,
            owner_session_id=owner_session_id,
            owner_type='script_execution',
            owner_job_id=owner_job_id,
            force=False,
        )
        if not release_result.get('released'):
            # Subordinate to a manual_control lock: nothing to release, but the
            # "campaign running" annotation must not outlive the failed launch.
            clear_device_active_script(
                host_name=host_name, device_id=device_id, owner_job_id=owner_job_id
            )
        if release_result.get('success'):
            emit_system_update('lock_changed', {
                'host_name': host_name,
                'device_id': device_id,
                'is_locked': False,
                'lock_info': release_result.get('lock_info'),
            })
        return jsonify({
            'success': False,
            'error': 'Invalid callback_url. Use absolute http/https URL or configure WEBHOOK_BASE_URL for relative paths.'
        }), 400

    # Host should always callback to server; server handles external webhook fanout.
    campaign_config['callback_url'] = buildServerUrl('server/campaigns/executionComplete')
    campaign_config['external_callback_url'] = callback_url
    campaign_config['callback_on_script_complete'] = bool(data.get('callback_on_script_complete', False))
    campaign_config['callback_on_campaign_complete'] = bool(data.get('callback_on_campaign_complete', True))
    campaign_config['lock_owner_session_id'] = owner_session_id
    campaign_config['lock_owner_job_id'] = owner_job_id

    query_params = {'team_id': team_id}
    response_data, status_code = call_host(
        host_info,
        '/host/campaigns/execute',
        method='POST',
        data=campaign_config,
        query_params=query_params,
        timeout=120,
    )
    if status_code not in (200, 202) or not response_data.get('success'):
        # Mark adhoc execution as failed
        if adhoc_exec_id:
            try:
                complete_adhoc_execution(get_supabase_client(), adhoc_exec_id, success=False)
                emit_system_update('deployment_changed', {
                    'domain': 'deployment', 'action': 'execution_completed',
                    'execution_id': adhoc_exec_id,
                })
            except Exception:
                pass
        release_result = release_device_lock(
            host_name=host_name,
            device_id=device_id,
            owner_session_id=owner_session_id,
            owner_type='script_execution',
            owner_job_id=owner_job_id,
            force=False,
        )
        if not release_result.get('released'):
            # Subordinate to a manual_control lock: nothing to release, but the
            # "campaign running" annotation must not outlive the failed launch.
            clear_device_active_script(
                host_name=host_name, device_id=device_id, owner_job_id=owner_job_id
            )
        if release_result.get('success'):
            emit_system_update('lock_changed', {
                'host_name': host_name,
                'device_id': device_id,
                'is_locked': False,
                'lock_info': release_result.get('lock_info'),
            })
        return jsonify(response_data), status_code

    return jsonify({
        **response_data,
        'lock_info': lock_result.get('lock_info'),
        'deployment_execution_id': adhoc_exec_id,
    }), status_code


@server_campaign_execution_bp.route('/executionComplete', methods=['POST'])
@handle_route_exceptions('server_campaign_execution:execution_complete')
def campaign_execution_complete():
    """
    Completion callback from host campaign execution.
    Fan out to socket events and optional external callback webhook(s).
    """
    data = request.get_json() or {}
    execution_id = data.get('execution_id')
    status = data.get('status', 'completed')
    campaign_id = data.get('campaign_id')
    result = data.get('result') or {}
    error = data.get('error')
    host_name = data.get('host_name')
    device_id = data.get('device_id')
    team_id = data.get('team_id')
    callback_url = data.get('external_callback_url')
    callback_on_script_complete = bool(data.get('callback_on_script_complete', False))
    callback_on_campaign_complete = bool(data.get('callback_on_campaign_complete', True))
    lock_owner_session_id = data.get('lock_owner_session_id')
    lock_owner_job_id = data.get('lock_owner_job_id')

    if not execution_id:
        return jsonify({'success': False, 'error': 'execution_id is required'}), 400

    # Update adhoc deployment_execution row if present
    dep_exec_id = data.get('deployment_execution_id')
    if dep_exec_id:
        try:
            campaign_success = status == 'completed' and not bool(error)
            complete_adhoc_execution(get_supabase_client(), dep_exec_id, success=campaign_success)
            emit_system_update('deployment_changed', {
                'domain': 'deployment', 'action': 'execution_completed',
                'execution_id': dep_exec_id,
            })
            print(f"[@server_campaign:execution_complete] Updated adhoc execution {dep_exec_id}")
        except Exception as adhoc_err:
            print(f"[@server_campaign:execution_complete] Adhoc execution update failed (non-fatal): {adhoc_err}")

    if host_name and device_id:
        # Check if lock is still manual_control (campaign ran under umbrella)
        current_lock_info = get_device_lock_info(host_name, device_id)
        if current_lock_info and current_lock_info.get('owner_type') == 'manual_control':
            print(f"[@server_campaign:execution_complete] Device {host_name}:{device_id} under manual_control umbrella, skipping unlock")
            # Lock stays with the user; drop only the "campaign running" annotation.
            clear_result = clear_device_active_script(
                host_name=host_name, device_id=device_id, owner_job_id=lock_owner_job_id
            )
            if clear_result.get('cleared'):
                emit_system_update('lock_changed', {
                    'host_name': host_name,
                    'device_id': device_id,
                    'is_locked': True,
                    'lock_info': clear_result.get('lock_info'),
                })
        else:
            release_result = release_device_lock(
                host_name=host_name,
                device_id=device_id,
                owner_session_id=lock_owner_session_id,
                owner_type='script_execution',
                owner_job_id=lock_owner_job_id,
                force=False,
            )
            if release_result.get('success'):
                emit_system_update('lock_changed', {
                    'host_name': host_name,
                    'device_id': device_id,
                    'is_locked': False,
                    'lock_info': release_result.get('lock_info'),
                })
            else:
                print(
                    f"[@server_campaign:execution_complete] Device unlock for {host_name}:{device_id} failed: "
                    f"{release_result.get('error')}"
                )

    # Per-script webhook fanout (optional). Keeps detailed parity with historical polling detail.
    if callback_url and callback_on_script_complete:
        script_executions = result.get('script_executions') or []
        for index, script_result in enumerate(script_executions):
            notify_completion(
                {
                    'task_id': f'{execution_id}:script:{index}',
                    'execution_type': 'campaign_script',
                    'status': 'completed' if script_result.get('success') else 'failed',
                    'success': bool(script_result.get('success')),
                    'host_name': host_name,
                    'device_id': device_id,
                    'team_id': team_id,
                    'deployment_id': campaign_id,
                    'result': {
                        'campaign_execution_id': execution_id,
                        'campaign_id': campaign_id,
                        'script_execution': script_result,
                    },
                    'error': script_result.get('error'),
                    'action': 'campaign_script_complete',
                    'timestamp': time.time(),
                },
                callback_url=callback_url,
            )

    # Campaign-level completion fanout
    notify_completion(
        {
            'task_id': execution_id,
            'execution_type': 'campaign',
            'status': status,
            'success': status == 'completed' and not bool(error),
            'host_name': host_name,
            'device_id': device_id,
            'team_id': team_id,
            'deployment_id': campaign_id,
            'result': result,
            'error': error,
            'action': 'campaign_execution_complete',
            'timestamp': data.get('completed_at', time.time()),
        },
        callback_url=callback_url if callback_on_campaign_complete else None,
    )

    return jsonify({'success': True}), 200



@server_campaign_execution_bp.route('/results', methods=['GET'])
@handle_route_exceptions('server_campaign_execution:get_results')
def get_all_campaign_results():
    """Get all campaign results for a team"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    campaign_id = request.args.get('campaign_id')
    status = request.args.get('status')
    limit = int(request.args.get('limit', 50))
    results = get_campaign_results(team_id=team_id, campaign_id=campaign_id, status=status, limit=limit)
    if not results['success']:
        return jsonify({'success': False, 'error': results.get('error', 'Failed to get campaign results')}), 500
    return jsonify({
        'success': True,
        'campaign_results': results['data'],
        'count': len(results['data'])
    }), 200


@server_campaign_execution_bp.route('/results/<campaign_result_id>', methods=['GET'])
@handle_route_exceptions('server_campaign_execution:get_result_details')
def get_campaign_result_details(campaign_result_id: str):
    """Get detailed campaign result including script executions"""
    team_id = request.args.get('team_id')
    if not team_id:
        return jsonify({'success': False, 'error': 'team_id is required'}), 400
    campaign_result = get_campaign_execution_with_scripts(campaign_result_id)
    if not campaign_result:
        return jsonify({'success': False, 'error': 'Campaign execution not found'}), 404
    return jsonify({
        'success': True,
        'campaign_result': campaign_result,
        'script_executions': campaign_result.get('script_results', [])
    }), 200
