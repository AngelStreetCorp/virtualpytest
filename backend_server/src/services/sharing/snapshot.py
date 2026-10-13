"""Build the sanitized payload of a run share snapshot (TASK-42 §4.3 Sharing).

The payload is assembled server-side from an ALLOWLIST; nothing from the
stored rows is copied wholesale. It contains a display title, normalized
status, counts, durations, safe label names and redacted per-attempt rows
(name, status, duration, start time, environment).

Never included: host or device names, IPs, raw metadata, error messages, logs,
report/evidence URLs (R2/MinIO), AI review, Jira content, ids of other objects.
Free text that is included (titles, names, labels) is scrubbed of IP
addresses, URLs, e-mail addresses and token-like strings.

The source data is read with the caller's full scope (team + this server's
hosts + workspace filter), so a snapshot can never contain more than the
creator could see.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from backend_server.src.services.analytics.scope import RunScope, derive_status
from shared.src.lib.database.run_management_db import pick_latest_per_group
from shared.src.lib.database.run_rpc import get_supabase
from shared.src.lib.database.in_filter import chunked_in

PAYLOAD_SCHEMA_VERSION = 1
MAX_ROWS = 500
MAX_TEXT = 200
REDACTED = '[redacted]'
STATUS_KEYS = ('passed', 'failed', 'running', 'pending', 'skipped', 'cancelled', 'unknown')

_RESULT_COLUMNS = ('id, team_id, script_name, script_type, userinterface_name, environment, '
                   'host_name, device_name, success, execution_time_ms, started_at, completed_at, discard')

_SCRUB_PATTERNS = [
    re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s"\'<>]+', re.IGNORECASE),             # URLs
    re.compile(r'\bwww\.[^\s"\'<>]+', re.IGNORECASE),
    re.compile(r'\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b'),                                # e-mail
    re.compile(r'\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*'),                             # JWT
    re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b'),                         # IPv4[:port]
    re.compile(r'\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{0,4}\b', re.IGNORECASE),          # IPv6
    re.compile(r'\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][\w-]{8,}\b', re.IGNORECASE),    # API keys
    re.compile(r'\b[0-9a-f]{32,}\b', re.IGNORECASE),                                 # hex secrets
    # opaque mixed-case tokens (base64/base64url); lowercase snake_case names are kept
    re.compile(r'\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*[A-Z])[A-Za-z0-9_-]{24,}\b'),
]


def scrub_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    for pattern in _SCRUB_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = ''.join(ch for ch in text if ch.isprintable())
    return text[:MAX_TEXT]


def _counts(statuses: Sequence[str]) -> Dict[str, int]:
    counts = {key: 0 for key in STATUS_KEYS}
    counts['total'] = len(statuses)
    for status in statuses:
        counts[status if status in STATUS_KEYS else 'unknown'] += 1
    return counts


def _row(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'name': scrub_text(result.get('script_name')),
        'status': derive_status(result),
        'execution_time_ms': result.get('execution_time_ms'),
        'started_at': result.get('started_at'),
        'environment': result.get('environment') if result.get('environment') in ('dev', 'test', 'prod') else None,
    }


def _label_names(team_id: str, result_ids: Sequence[str]) -> List[str]:
    if not result_ids:
        return []
    supabase = get_supabase()
    links = chunked_in(
        lambda chunk: supabase.table('script_result_labels').select('run_label_id')
        .eq('team_id', team_id).in_('script_result_id', chunk),
        list(result_ids)[:MAX_ROWS])
    label_ids = sorted({str(link['run_label_id']) for link in links if link.get('run_label_id')})
    if not label_ids:
        return []
    labels = (supabase.table('run_label_definitions').select('name')
              .eq('team_id', team_id).in_('id', label_ids).execute()).data or []
    return sorted({scrub_text(label.get('name')) for label in labels if label.get('name')})


def _fetch_results(scope: RunScope, *, ids: Optional[Sequence[str]] = None,
                   run_group_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if not scope.host_names:
        return []
    query = (get_supabase().table('script_results').select(_RESULT_COLUMNS)
             .eq('team_id', scope.team_id).in_('host_name', list(scope.host_names)))
    if ids is not None:
        if not ids:
            return []
        query = query.in_('id', list(ids))
    if run_group_id is not None:
        query = query.eq('run_group_id', run_group_id)
    rows = query.order('started_at', desc=True).limit(MAX_ROWS + 1).execute().data or []
    return [r for r in rows if scope.allows_result(r)]


def _envelope(kind: str, title: Any, status: str, rows: List[Dict[str, Any]], counts: Dict[str, int],
              labels: List[str], *, started_at: Any = None, completed_at: Any = None,
              execution_time_ms: Optional[int] = None, **extra: Any) -> Dict[str, Any]:
    if execution_time_ms is None:
        durations = [r['execution_time_ms'] for r in rows if isinstance(r.get('execution_time_ms'), int)]
        execution_time_ms = sum(durations) if durations else None
    payload = {
        'schema_version': PAYLOAD_SCHEMA_VERSION,
        'kind': kind,
        'title': scrub_text(title) or 'Run',
        'status': status,
        'counts': counts,
        'durations': {
            'started_at': started_at,
            'completed_at': completed_at,
            'execution_time_ms': execution_time_ms,
        },
        'safe_labels': labels,
        'rows': [_row(r) for r in rows[:MAX_ROWS]],
        'rows_truncated': len(rows) > MAX_ROWS,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    payload.update(extra)
    return payload


def build_script_payload(scope: RunScope, script_result_id: str) -> Optional[Dict[str, Any]]:
    rows = _fetch_results(scope, ids=[script_result_id])
    if not rows:
        return None
    result = rows[0]
    status = derive_status(result)
    return _envelope('script', result.get('script_name'), status, rows, _counts([status]),
                     _label_names(scope.team_id, [str(result['id'])]),
                     started_at=result.get('started_at'),
                     completed_at=result.get('completed_at') if status != 'unknown' else None,
                     execution_time_ms=result.get('execution_time_ms'))


def build_group_payload(scope: RunScope, group_id: str) -> Optional[Dict[str, Any]]:
    groups = (get_supabase().table('run_groups').select('id, name')
              .eq('team_id', scope.team_id).eq('id', group_id).limit(1).execute()).data or []
    if not groups:
        return None
    members = _fetch_results(scope, run_group_id=group_id)
    latest = pick_latest_per_group(members)
    counts = _counts([derive_status(r) for r in latest])
    status = 'unknown' if not latest else (
        'failed' if counts['failed'] else ('passed' if counts['passed'] == counts['total'] else 'unknown'))
    return _envelope('group', groups[0].get('name'), status, members, counts,
                     _label_names(scope.team_id, [str(r['id']) for r in members]),
                     started_at=min((r['started_at'] for r in members if r.get('started_at')), default=None),
                     merge='latest', attempts_total=len(members))


def build_campaign_payload(scope: RunScope, campaign_execution_id: str) -> Optional[Dict[str, Any]]:
    executions = (get_supabase().table('campaign_executions')
                  .select('id, team_id, campaign_name, host_name, status, success, started_at, '
                          'completed_at, execution_time_ms, script_configurations, script_result_ids')
                  .eq('team_id', scope.team_id).eq('id', campaign_execution_id).limit(1)
                  .execute()).data or []
    if not executions or not scope.allows_host(executions[0].get('host_name')):
        return None
    execution = executions[0]
    child_ids = [str(i) for i in (execution.get('script_result_ids') or [])]
    children = _fetch_results(scope, ids=child_ids)
    configured = execution.get('script_configurations')
    configured_total = len(configured) if isinstance(configured, list) else len(child_ids)
    statuses = [derive_status(r) for r in children]
    statuses += ['unknown'] * max(configured_total - len(children), 0)
    raw_status = (execution.get('status') or '').lower()
    status = {'completed': 'passed' if execution.get('success') else 'failed',
              'failed': 'failed', 'cancelled': 'cancelled', 'aborted': 'cancelled',
              'running': 'running', 'pending': 'pending'}.get(raw_status, 'unknown')
    return _envelope('campaign', execution.get('campaign_name'), status, children, _counts(statuses),
                     _label_names(scope.team_id, [str(r['id']) for r in children]),
                     started_at=execution.get('started_at'), completed_at=execution.get('completed_at'),
                     execution_time_ms=execution.get('execution_time_ms'))


BUILDERS = {
    'script': build_script_payload,
    'group': build_group_payload,
    'campaign': build_campaign_payload,
}


def payload_csv_rows(payload: Dict[str, Any]) -> List[List[Any]]:
    return [[r.get('name'), r.get('status'), r.get('execution_time_ms'), r.get('started_at'), r.get('environment')]
            for r in payload.get('rows') or []]


CSV_HEADERS = ('name', 'status', 'execution_time_ms', 'started_at', 'environment')
