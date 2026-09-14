"""
Ad-hoc execution persistence.

Creates one-shot deployment + deployment_execution rows so that every direct
"Run Now" execution (script or campaign) is visible in
/server/deployment/executions/recent and survives page refresh.
"""

import time
from datetime import datetime, timezone


def create_adhoc_execution(supabase, *, team_id, host_name, device_id, script_name,
                           campaign_id=None, parameters=None, userinterface_name=None,
                           rerun_payload=None):
    """
    Insert a one-shot deployment and a 'running' deployment_execution row.

    The deployment is created with status='completed' so the host scheduler
    never picks it up as a recurring job.  The deployment_executions join in
    /recent does not filter on deployment status, so the row still appears.

    `rerun_payload` (optional dict) is the full launch-time config that the
    "Last Executions" rerun icon needs to relaunch this row in one click after
    a page reload.

    Returns (deployment_row, execution_row).
    """
    now = datetime.now(timezone.utc).isoformat()

    deployment_data = {
        'team_id': team_id,
        'name': f'{script_name}_{int(time.time())}',
        'host_name': host_name,
        'device_id': device_id,
        'script_name': script_name,
        'userinterface_name': userinterface_name or '',
        'cron_expression': '0 0 1 1 *',
        'max_executions': 1,
        'status': 'completed',
    }
    if campaign_id:
        deployment_data['campaign_id'] = campaign_id
    if parameters:
        deployment_data['parameters'] = parameters
    if rerun_payload is not None:
        deployment_data['rerun_payload'] = rerun_payload

    deployment = supabase.table('deployments').insert(deployment_data).execute().data[0]

    execution = supabase.table('deployment_executions').insert({
        'deployment_id': deployment['id'],
        'scheduled_at': now,
        'started_at': now,
        'status': 'running',
    }).execute().data[0]

    return deployment, execution


def complete_adhoc_execution(supabase, execution_id, *, success, script_result_id=None):
    """
    Mark an ad-hoc deployment_execution as completed/failed.
    """
    now = datetime.now(timezone.utc).isoformat()
    update = {
        'completed_at': now,
        'status': 'completed' if success else 'failed',
        'success': success,
    }
    if script_result_id:
        update['script_result_id'] = script_result_id
    supabase.table('deployment_executions').update(update).eq('id', execution_id).execute()
