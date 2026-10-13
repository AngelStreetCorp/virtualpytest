"""Run-group rerun planning and dispatch (TASK-42).

Planning reuses the TestReports rerun contract: a result's launch config is the
deployment ``rerun_payload`` joined to it, else the launch fields recorded on
``metadata`` (same rules as ``buildRerunPayloadFromResult`` in
frontend/src/utils/executionUtils.tsx). Dispatch reuses the existing execution
orchestration: a one-shot deployment through ``create_deployment_record`` —
the queue /server/script/execute itself falls back to — so the host scheduler
runs each script when its device is free and records a new script_results row.
Previous attempts are never modified.

Never replayed: manual runs (script_type 'manual'). Not dispatchable from the
server: testcase runs (they need the builder's graph execution path, which
holds the device lock synchronously) — they are reported as skipped.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend_server.src.services.analytics.scope import derive_status
from shared.src.lib.database.run_management_db import identity_of, merge_latest_with_attempts

RERUN_MODES = ('all', 'failures')


def is_manual_script_result(row: Dict[str, Any]) -> bool:
    return str(row.get('script_type') or '').strip().lower() == 'manual'


def rerun_payload_from_result(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Launch config of a stored result, or None when none was recorded."""
    payload = row.get('rerun_payload')
    if isinstance(payload, dict) and payload.get('type') in ('script', 'testcase'):
        return payload
    metadata = row.get('metadata') if isinstance(row.get('metadata'), dict) else None
    if not metadata:
        return None
    device_id = metadata.get('device_id') or 'host'
    if row.get('script_type') == 'testcase':
        if metadata.get('unsaved') is True or not metadata.get('testcase_id'):
            return None
        return {
            'type': 'testcase',
            'scriptName': row.get('script_name'),
            'hostName': row.get('host_name'),
            'deviceId': device_id,
            'testcaseId': str(metadata.get('testcase_id')),
            'testcaseVersionNumber': metadata.get('testcase_version'),
        }
    if not isinstance(metadata.get('parameters'), str):
        return None
    payload = {
        'type': 'script',
        'scriptName': row.get('script_name'),
        'hostName': row.get('host_name'),
        'deviceId': device_id,
        'parameters': metadata.get('parameters'),
    }
    if metadata.get('virtual_script_id'):
        payload['virtualScriptId'] = metadata.get('virtual_script_id')
    return payload


def select_rerun_targets(members: Sequence[Dict[str, Any]], mode: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pick the attempts to replay. Returns (targets, skipped).

    ``all``: the latest attempt of every logical identity (script + UI +
    environment + host + device). ``failures``: the latest non-discarded
    attempt of every identity, kept only when it is a terminal failure
    (``derive_status``) — an attempt still running is never relaunched.
    Manual identities are always skipped.
    """
    if mode not in RERUN_MODES:
        raise ValueError(f'mode must be one of {RERUN_MODES}')
    pool = [m for m in members if not (mode == 'failures' and m.get('discard'))]
    targets: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for entry in merge_latest_with_attempts(pool):
        latest = entry['latest']
        ref = {'script_result_id': str(latest.get('id')), 'script_name': latest.get('script_name'),
               'host_name': latest.get('host_name'), 'device_name': latest.get('device_name')}
        if is_manual_script_result(latest):
            skipped.append({**ref, 'reason': 'manual_run'})
        elif mode == 'failures':
            status = derive_status(latest)
            if status == 'failed':
                targets.append(latest)
            elif status != 'passed':
                skipped.append({**ref, 'reason': 'latest_attempt_not_terminal'})
        else:
            targets.append(latest)
    if mode == 'failures':
        discarded_only = {identity_of(m) for m in members if m.get('discard')} - {identity_of(m) for m in pool}
        for identity in sorted(discarded_only, key=lambda i: tuple(str(x) for x in i)):
            skipped.append({'script_name': identity[0], 'host_name': identity[3], 'device_name': identity[4],
                            'script_result_id': None, 'reason': 'only_discarded_attempts'})
    return targets, skipped


def dispatch_rerun(team_id: str, row: Dict[str, Any], payload: Dict[str, Any],
                   create_deployment: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """Queue one script rerun as a one-shot deployment on its original target."""
    script_name = payload.get('scriptName') or row.get('script_name')
    host_name = payload.get('hostName') or row.get('host_name')
    device_id = payload.get('deviceId')
    deployment = create_deployment(team_id, {
        'name': f'rerun_{script_name}_{host_name}_{device_id}_{int(time.time() * 1000)}',
        'host_name': host_name,
        'device_id': device_id,
        'script_name': script_name,
        'userinterface_name': row.get('userinterface_name') or '',
        'parameters': payload.get('parameters') or '',
        'cron_expression': '0 0 1 1 *',
        'max_executions': 1,
        'virtual_script_id': payload.get('virtualScriptId'),
        'environment': row.get('environment'),
        'rerun_payload': payload,
    })
    return {
        'source_script_result_id': str(row.get('id')),
        'script_name': script_name,
        'host_name': host_name,
        'device_id': device_id,
        'deployment_id': deployment.get('id'),
    }


__all__ = [
    'RERUN_MODES', 'is_manual_script_result', 'rerun_payload_from_result',
    'select_rerun_targets', 'dispatch_rerun',
]
