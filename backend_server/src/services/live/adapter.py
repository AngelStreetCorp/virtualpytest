"""Live run status adapter over the existing script task records (TASK-42 §4.3 Live).

Source of truth: the server's in-memory ``task_manager`` entry created by
``POST /server/script/execute`` (params: team_id, host_name, device_id,
script_name, adhoc_exec_id), the latest ``/server/script/progress`` event it
now keeps, and the ``/server/script/taskComplete`` callback result. The durable
hand-off is the completion's ``result.script_result_id`` (or the adhoc
``deployment_executions.script_result_id``), confirmed in ``script_results``
for the same team before it is exposed. ``metadata.execution_id`` is not
written by the script executor, so it is not used.

Rules:
* A task is visible only when its recorded team equals the caller's team and
  its host/device are inside the caller's scope; otherwise it does not exist.
* Missing task (never existed, server restarted, cleaned up after an hour) is
  ``unknown`` — never completed.
* No progress for ``STALE_AFTER_SECONDS`` while running sets ``stale``.
* Totals/ETA are null unless the producer reported step totals.
* Stop calls the host's ``/host/script/abort`` through ``call_host`` with the
  task id, so only the process launched for this task can be killed; the
  task's own completion callback then records the end. Releasing a device lock
  is not used as cancellation.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend_server.src.services.analytics.scope import RunScope, device_display_name
from shared.src.lib.database.run_rpc import get_supabase

STALE_AFTER_SECONDS = 120
STOP_PERMISSION = 'execution.run:run_test'


def _iso(epoch: Optional[float]) -> Optional[str]:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def task_device_name(task: Dict[str, Any], hosts: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """The task's device as results and workspace scope name it (display name)."""
    params = task.get('params') or {}
    return device_display_name(hosts, params.get('host_name'), params.get('device_id'))


def visible_task(task: Optional[Dict[str, Any]], scope: RunScope, hosts: Dict[str, Dict[str, Any]]) -> bool:
    """Task records carry the host-local device id; scope device keys are
    ``host:device_name``, so the id is translated with the registered host's
    device list before the check (an unregistered device keeps its id)."""
    if not task:
        return False
    params = task.get('params') or {}
    if str(params.get('team_id') or '') != scope.team_id:
        return False
    return scope.allows_device(params.get('host_name'), task_device_name(task, hosts))


def map_status(task: Dict[str, Any]) -> str:
    raw = task.get('status')
    if raw == 'started':
        return 'running'
    if raw == 'completed':
        return 'passed'
    if raw == 'failed':
        return 'cancelled' if task.get('stop_requested_at') else 'failed'
    return 'unknown'


def durable_result_id(team_id: str, task: Dict[str, Any]) -> Optional[str]:
    if task.get('status') not in ('completed', 'failed'):
        return None
    candidates = []
    result = task.get('result') or {}
    if result.get('script_result_id'):
        candidates.append(str(result['script_result_id']))
    adhoc_exec_id = (task.get('params') or {}).get('adhoc_exec_id')
    supabase = get_supabase()
    if not candidates and adhoc_exec_id:
        rows = (supabase.table('deployment_executions').select('script_result_id')
                .eq('id', adhoc_exec_id).limit(1).execute()).data or []
        if rows and rows[0].get('script_result_id'):
            candidates.append(str(rows[0]['script_result_id']))
    if not candidates:
        return None
    rows = (supabase.table('script_results').select('id')
            .eq('team_id', team_id).eq('id', candidates[0]).limit(1).execute()).data or []
    return str(rows[0]['id']) if rows else None


def snapshot(task_id: str, task: Dict[str, Any], scope: RunScope, *, can_stop_permission: bool,
             hosts: Dict[str, Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    current = now or time.time()
    params = task.get('params') or {}
    status = map_status(task)
    created = task.get('created_at')
    completed = task.get('completed_at')
    progress_raw = task.get('progress') or None
    progress = None
    eta_ms = None
    if progress_raw:
        done = progress_raw.get('step_number')
        total = progress_raw.get('total_steps')
        progress = {'completed': done if isinstance(done, int) else None,
                    'total': total if isinstance(total, int) and total > 0 else None,
                    'message': progress_raw.get('message')}
    end = completed if status != 'running' else current
    elapsed_ms = int((end - created) * 1000) if created and end else None
    if (status == 'running' and progress and progress['completed'] and progress['total']
            and elapsed_ms is not None and progress['completed'] < progress['total']):
        per_step = elapsed_ms / progress['completed']
        eta_ms = int(per_step * (progress['total'] - progress['completed']))
    last_signal = task.get('progress_at') or created
    stale = bool(status == 'running' and last_signal and current - last_signal > STALE_AFTER_SECONDS)
    return {
        'task_id': task_id,
        'status': status,
        'stale': stale,
        'script_name': params.get('script_name'),
        'host_name': params.get('host_name'),
        'device_id': params.get('device_id'),
        'device_name': task_device_name(task, hosts),
        'started_at': _iso(created),
        'elapsed_ms': elapsed_ms,
        'progress': progress,
        'eta_ms': eta_ms,
        'updated_at': _iso(completed or task.get('progress_at') or created),
        'script_result_id': durable_result_id(scope.team_id, task),
        'stop_requested': bool(task.get('stop_requested_at')),
        'can_stop': bool(status == 'running' and can_stop_permission),
    }


def unknown(task_id: str) -> Dict[str, Any]:
    return {
        'task_id': task_id, 'status': 'unknown', 'stale': True, 'script_name': None,
        'host_name': None, 'device_id': None, 'device_name': None, 'started_at': None, 'elapsed_ms': None,
        'progress': None, 'eta_ms': None, 'updated_at': None, 'script_result_id': None,
        'stop_requested': False, 'can_stop': False,
    }


def request_stop(task_id: str, task: Dict[str, Any], host_info: Dict[str, Any], actor: str,
                 task_manager: Any, call_host: Any) -> Dict[str, Any]:
    params = task.get('params') or {}
    response, status_code = call_host(
        host_info, '/host/script/abort', method='POST',
        data={'device_id': params.get('device_id'), 'task_id': task_id}, timeout=30)
    response = response if isinstance(response, dict) else {}
    if status_code != 200 or not response.get('success'):
        return {'http': 502, 'body': {'success': False, 'status': map_status(task),
                                      'error': response.get('error') or 'host did not confirm the stop'}}
    if not response.get('aborted'):
        current = task_manager.get_task(task_id) or task
        return {'http': 409, 'body': {'success': False, 'status': map_status(current),
                                      'error': response.get('message') or 'no running process for this task'}}
    # Recorded once the host confirmed the kill; if the completion callback won the
    # race, the task already reads 'failed' and stays that way.
    task_manager.mark_stop_requested(task_id, actor)
    return {'http': 202, 'body': {'success': True, 'status': 'running', 'stop_requested': True}}
