"""
MCP responses for async executions (testcases and scripts).

Every response carries a short text for chat clients and `structuredContent` for
programmatic clients:
    {execution_id, kind, status, done, passed, report_url, logs_url,
     execution_time_ms, error, ...}
`done` false means: call the status tool again.
"""

from typing import Any, Dict, Optional

from .execution_status_constants import (
    DONE_STATES,
    STATE_ABORTED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_UNKNOWN,
)


# Labels kept as the old blocking replies wrote them ("✅ Test case ... completed / Result: PASSED (4.0s)"),
# so clients that read the text keep working.
_KIND_LABELS = {'testcase': 'Test case', 'script': 'Script'}


def _links(report_url: str, logs_url: str) -> str:
    text = ''
    if report_url:
        text += f"\n📄 Report: [View Report]({report_url})"
    if logs_url:
        text += f"\n📋 Logs: [View Logs]({logs_url})"
    return text


def _response(text: str, structured: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": is_error,
    }


def build_status(execution_id: str, kind: str, status: str, passed: Optional[bool] = None,
                 report_url: str = '', logs_url: str = '', execution_time_ms: Optional[int] = None,
                 error: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    structured = {
        'execution_id': execution_id,
        'kind': kind,
        'status': status,
        'done': status in DONE_STATES,
        'passed': passed,
        'report_url': report_url or None,
        'logs_url': logs_url or None,
        'execution_time_ms': execution_time_ms,
        'error': error,
    }
    structured.update(extra)
    return structured


def started_response(structured: Dict[str, Any], name: str, status_tool: str) -> Dict[str, Any]:
    kind = _KIND_LABELS.get(structured['kind'], structured['kind'])
    text = (f"▶️ {kind} '{name}' started on {structured.get('host_name')}:{structured.get('device_id')}\n"
            f"execution_id: {structured['execution_id']}\n"
            f"Call {status_tool}(execution_id='{structured['execution_id']}') until done is true.")
    return _response(text, structured)


def status_response(structured: Dict[str, Any], name: str = '') -> Dict[str, Any]:
    kind = _KIND_LABELS.get(structured['kind'], structured['kind'])
    label = f"{kind} '{name}'" if name else kind
    status = structured['status']
    seconds = (structured.get('execution_time_ms') or 0) / 1000

    if status == STATE_COMPLETED:
        verdict = {True: 'PASSED', False: 'FAILED', None: 'UNKNOWN'}[structured.get('passed')]
        text = f"✅ {label} completed\nResult: {verdict} ({seconds:.1f}s)\n"
        if structured.get('error') and structured.get('passed') is False:
            text += f"Error: {structured['error']}\n"
    elif status == STATE_FAILED:
        text = f"❌ {label} failed: {structured.get('error') or 'execution failed'}\n"
    elif status == STATE_ABORTED:
        text = f"⏹️ {label} aborted\n"
    elif status == STATE_UNKNOWN:
        text = (f"⏳ {label} status unavailable right now ({structured.get('error')}); "
                f"the run goes on, read the status again\n")
    else:
        text = f"⏳ {label} {status}"
        if structured.get('current_block_id'):
            text += f" (block {structured['current_block_id']})"
        text += f"\nexecution_id: {structured['execution_id']}; call the status tool again\n"

    return _response(text + _links(structured.get('report_url'), structured.get('logs_url')), structured)


def unknown_execution_response(execution_id: str, kind: str, error: str) -> Dict[str, Any]:
    """The status read failed for a reason a retry won't fix (unknown id, bad request)."""
    return _response(f"❌ Status check failed for {kind} {execution_id}: {error}",
                     build_status(execution_id, kind, STATE_UNKNOWN, error=error), is_error=True)


def transient_read_response(execution_id: str, kind: str, error: str, name: str = '') -> Dict[str, Any]:
    return status_response(build_status(execution_id, kind, STATE_UNKNOWN, error=error), name)

