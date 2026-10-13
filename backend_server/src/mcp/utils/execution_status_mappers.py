"""
Map the server's raw status payloads to the normalised MCP status (see execution_status_formatter).

Testcase: GET /server/testcase/execution/<id>/status -> {'success', 'status': {status, result, error, current_block_id, elapsed_time_ms}}
Script:   GET /server/script/status/<task_id>        -> {'success', 'task': {status, result, error}}
"""

from typing import Any, Dict

from .execution_status_constants import (
    STATE_ABORTED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_RUNNING,
)
from .execution_status_formatter import build_status

KIND_TESTCASE = 'testcase'
KIND_SCRIPT = 'script'

_TESTCASE_STATES = {
    'completed': STATE_COMPLETED,
    'failed': STATE_FAILED,
    'error': STATE_FAILED,
    'aborted': STATE_ABORTED,
}

_SCRIPT_STATES = {
    'completed': STATE_COMPLETED,
    'failed': STATE_FAILED,
    'aborted': STATE_ABORTED,
}


def map_testcase_status(execution_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
    execution = response.get('status') if isinstance(response.get('status'), dict) else {}
    raw = execution.get('status')
    status = _TESTCASE_STATES.get(raw, STATE_RUNNING)
    result = execution.get('result') or {}
    passed = bool(result.get('success', True)) if status == STATE_COMPLETED else None
    if status == STATE_FAILED:
        passed = False
    return build_status(
        execution_id, KIND_TESTCASE, status,
        passed=passed,
        report_url=result.get('report_url', ''),
        logs_url=result.get('logs_url', ''),
        execution_time_ms=result.get('execution_time_ms', execution.get('elapsed_time_ms')),
        error=result.get('error') or execution.get('error'),
        current_block_id=execution.get('current_block_id'),
    )


def map_script_status(task_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
    task = response.get('task') if isinstance(response.get('task'), dict) else {}
    status = _SCRIPT_STATES.get(task.get('status'), STATE_RUNNING)
    result = task.get('result') or {}
    exit_code = result.get('exit_code')
    script_success = result.get('script_success')
    passed = None
    if status == STATE_COMPLETED:
        passed = script_success if script_success is not None else exit_code in (0, None)
    elif status == STATE_FAILED:
        passed = False
    return build_status(
        task_id, KIND_SCRIPT, status,
        passed=passed,
        report_url=result.get('report_url', ''),
        logs_url=result.get('logs_url', ''),
        execution_time_ms=result.get('execution_time_ms'),
        error=task.get('error') or (result.get('error') if status != STATE_COMPLETED else None),
        exit_code=exit_code,
        script_success=script_success,
    )
