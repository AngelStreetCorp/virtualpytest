"""Run summary aggregation (TASK-42): pure functions over persisted execution rows.

Statuses come only from evidence:
  - a script_results row is inserted when a run STARTS (success=false, no
    duration) and completed later, so its verdict is ``derive_status``:
    passed on success, failed only once it recorded an execution time,
    otherwise unknown — the same rule every run-management reader uses;
  - a campaign child is the script result linked through
    campaign_executions.script_result_ids, or a skip recorded by the campaign
    executor in campaign_executions.metadata.script_outcomes; a planned script
    with neither stays unknown;
  - nothing is inferred from names, timestamps or log lines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from backend_server.src.services.analytics.scope import derive_status

STATUSES = ('passed', 'failed', 'running', 'pending', 'skipped', 'cancelled', 'unknown')
TREND_DEFAULT_DAYS = 30
TREND_MAX_DAYS = 90


def campaign_status(row: Dict[str, Any]) -> str:
    """Verdict of one campaign_executions row (skip flag, then status column + success)."""

    def flag_on(value: Any) -> bool:
        """A skip flag as the database and the API spell it: true, 1 or 'true'."""
        if isinstance(value, str):
            return value.strip().lower() in {'true', '1', 'yes'}
        return value is True or value == 1

    # A campaign whose deployment never started (device busy, device locked by another
    # owner, device queue full) is skipped, not broken: the platform's own health must
    # not read it as a failure. The flag is the authority — the status column keeps its
    # own meaning, so a cancelled campaign reads as cancelled unless the flag says the
    # night never ran (BUG-0898).
    metadata = row.get('metadata') or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if flag_on(row.get('skipped')) or flag_on(metadata.get('skipped')):
        return 'skipped'
    status = str(row.get('status') or '').lower()
    if status in ('running', 'pending'):
        return status
    if status in ('cancelled', 'aborted'):
        return 'cancelled'
    if status == 'failed':
        return 'failed'
    if status == 'completed':
        return 'passed' if row.get('success') is True else 'failed'
    return 'unknown'


def count_statuses(statuses: Iterable[str]) -> Dict[str, int]:
    counts = {s: 0 for s in STATUSES}
    total = 0
    for status in statuses:
        counts[status if status in counts else 'unknown'] += 1
        total += 1
    counts['total'] = total
    return counts


def paginate(items: Sequence[Any], limit: int, offset: int) -> Dict[str, Any]:
    return {
        'items': list(items[offset:offset + limit]),
        'total': len(items),
        'limit': limit,
        'offset': offset,
    }


def result_child(row: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    """A child row (RunChild in frontend/src/types/reports/index.ts)."""
    child = {
        'script_result_id': str(row.get('id')),
        'name': row.get('script_name'),
        'script_type': row.get('script_type'),
        'status': derive_status(row),
        'userinterface_name': row.get('userinterface_name'),
        'environment': row.get('environment'),
        'host_name': row.get('host_name'),
        'device_name': row.get('device_name'),
        'started_at': row.get('started_at'),
        'completed_at': row.get('completed_at'),
        'execution_time_ms': row.get('execution_time_ms'),
        'discard': bool(row.get('discard')),
        'report_url': row.get('html_report_r2_url'),
        'logs_url': row.get('logs_r2_url'),
    }
    child.update(extra)
    return child


def placeholder_child(name: Optional[str], status: str, **extra: Any) -> Dict[str, Any]:
    """A campaign entry with no readable script result (skipped, or unknown)."""
    child = {
        'script_result_id': None, 'name': name, 'script_type': None, 'status': status,
        'userinterface_name': None, 'environment': None, 'host_name': None, 'device_name': None,
        'started_at': None, 'completed_at': None, 'execution_time_ms': None, 'discard': False,
        'report_url': None, 'logs_url': None,
    }
    child.update(extra)
    return child


def campaign_children(execution: Dict[str, Any], results_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Children of a campaign execution from its persisted relationships.

    With ``metadata.script_outcomes`` (one entry per executed position:
    execution_order, script_name, script_result_id, skipped, skip_reason) every
    planned position is accounted for. Without it (older executions) the linked
    results are listed in link order and the remaining planned positions are
    unknown — never assumed skipped or passed.
    """
    planned = execution.get('script_configurations') or []
    linked_ids = [str(i) for i in (execution.get('script_result_ids') or []) if i]
    metadata = execution.get('metadata') if isinstance(execution.get('metadata'), dict) else {}
    outcomes = metadata.get('script_outcomes')

    children: List[Dict[str, Any]] = []
    if isinstance(outcomes, list) and outcomes:
        seen_orders = set()
        for outcome in sorted((o for o in outcomes if isinstance(o, dict)),
                              key=lambda o: int(o.get('execution_order') or 0)):
            order = int(outcome.get('execution_order') or 0)
            seen_orders.add(order)
            sid = str(outcome.get('script_result_id') or '') or None
            if outcome.get('skipped') is True:
                children.append(placeholder_child(outcome.get('script_name'), 'skipped', position=order,
                                                  skip_reason=outcome.get('skip_reason')))
            elif sid and sid in results_by_id:
                children.append(result_child(results_by_id[sid], position=order))
            else:
                children.append(placeholder_child(outcome.get('script_name'), 'unknown', position=order,
                                                  script_result_id=sid,
                                                  unknown_reason='result not linked or outside this scope'))
        for index, config in enumerate(planned, start=1):
            if index not in seen_orders:
                children.append(placeholder_child((config or {}).get('script_name'), 'unknown', position=index,
                                                  unknown_reason='no recorded outcome'))
        children.sort(key=lambda c: c['position'])
        return children

    for index, sid in enumerate(linked_ids, start=1):
        row = results_by_id.get(sid)
        if row:
            children.append(result_child(row, position=None, link_order=index))
        else:
            children.append(placeholder_child(None, 'unknown', position=None, link_order=index,
                                              script_result_id=sid,
                                              unknown_reason='linked result missing or outside this scope'))
    for _ in range(max(len(planned) - len(linked_ids), 0)):
        children.append(placeholder_child(None, 'unknown', position=None,
                                          unknown_reason='planned script without a recorded outcome'))
    return children


def step_evidence(rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Navigation step evidence (execution_results rows, written only by
    NavigationExecutor for edge/node steps), labelled separately from the run
    verdict. None when the run recorded no navigation step."""
    if not rows:
        return None
    by_type: Dict[str, Dict[str, int]] = {}
    for row in rows:
        bucket = by_type.setdefault(str(row.get('execution_type') or 'unknown'),
                                    {'total': 0, 'passed': 0, 'failed': 0})
        bucket['total'] += 1
        bucket['passed' if row.get('success') is True else 'failed'] += 1
    return {
        'source': 'execution_results (navigation edge/node steps)',
        'total': len(rows),
        'passed': sum(b['passed'] for b in by_type.values()),
        'failed': sum(b['failed'] for b in by_type.values()),
        'by_type': by_type,
    }


def clamp_trend_days(raw: Any) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return TREND_DEFAULT_DAYS
    return min(max(days, 1), TREND_MAX_DAYS)


def trend_window(days: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """UTC day window ending today (inclusive): ``since`` is midnight of the first day."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    first_day = (now - timedelta(days=days - 1)).date()
    return {
        'days': days,
        'first_day': first_day,
        'since': datetime(first_day.year, first_day.month, first_day.day, tzinfo=timezone.utc).isoformat(),
    }


def _day_of(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def trend_series(attempts: Sequence[Dict[str, Any]], *, days: int, now: Optional[datetime] = None,
                 status_of=derive_status, identity: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Zero-filled UTC daily points with an explicit denominator.

    Each point: passed, failed, other (terminal but neither: skipped/cancelled)
    and total = passed + failed + other. Excluded and counted separately:
    discarded attempts and attempts that are not terminal (running, pending,
    unknown).
    """
    window = trend_window(days, now)
    points: Dict[str, Dict[str, Any]] = {}
    for i in range(days):
        day = (window['first_day'] + timedelta(days=i)).isoformat()
        points[day] = {'day': day, 'passed': 0, 'failed': 0, 'other': 0, 'total': 0}
    excluded = {'discarded': 0, 'not_terminal': 0}
    for attempt in attempts:
        day = _day_of(attempt.get('started_at'))
        if day not in points:
            continue
        if attempt.get('discard'):
            excluded['discarded'] += 1
            continue
        status = status_of(attempt)
        if status in ('passed', 'failed'):
            points[day][status] += 1
        elif status in ('skipped', 'cancelled'):
            points[day]['other'] += 1
        else:
            excluded['not_terminal'] += 1
            continue
        points[day]['total'] += 1
    return {
        'window_days': days,
        'from': window['first_day'].isoformat(),
        'to': (window['first_day'] + timedelta(days=days - 1)).isoformat(),
        'bucket': 'utc_day',
        'denominator': 'total = non-discarded terminal attempts that day (passed + failed + other)',
        'identity': identity,
        'excluded': excluded,
        'points': list(points.values()),
    }


def rollup_status(statuses: Sequence[str]) -> str:
    """Verdict of a set of latest attempts: failed if any failed, passed only if
    every one passed, otherwise unknown."""
    if not statuses:
        return 'unknown'
    if 'failed' in statuses:
        return 'failed'
    return 'passed' if all(s == 'passed' for s in statuses) else 'unknown'


__all__ = [
    'STATUSES', 'TREND_DEFAULT_DAYS', 'TREND_MAX_DAYS',
    'campaign_status', 'count_statuses', 'paginate', 'result_child',
    'placeholder_child', 'campaign_children', 'step_evidence', 'clamp_trend_days', 'trend_window',
    'trend_series', 'rollup_status',
]
