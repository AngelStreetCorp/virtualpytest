"""Quality insights over scoped execution history (TASK-42 §4.4).

* Flaky — per comparable identity (script name/type, UI, environment, host,
  device): adjacent pass<->fail transitions / (attempts - 1); only identities
  with >= 5 eligible attempts including at least one pass and one fail.
* Slow — nearest-rank p50/p95 of ``execution_time_ms`` over successful
  terminal attempts; >= 5 samples.
* Not executed in window — the currently runnable catalog visible to this
  server minus scripts with an eligible attempt in the window.

Eligible attempt = in scope, not discarded, terminal. Aggregation runs in SQL
(``rm_quality_*``) over the whole scoped window; every response reports the
window, the minimum sample and the sample sizes behind it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend_server.src.services.analytics.scope import RunScope
from shared.src.lib.database import run_quality_db

FLAKY_DEFAULT_WINDOW_DAYS = 14
SLOW_DEFAULT_WINDOW_DAYS = 30
NOT_EXECUTED_DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365
MIN_ATTEMPTS = 5

_IDENTITY_KEYS = ('script_name', 'script_type', 'userinterface_name', 'environment',
                  'host_name', 'device_name')


def window(days: int, now: Optional[datetime] = None) -> Dict[str, datetime]:
    until = now or datetime.now(timezone.utc)
    return {'since': until - timedelta(days=days), 'until': until}


def _identity(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in _IDENTITY_KEYS}


def _envelope(scope: RunScope, days: int, bounds: Dict[str, datetime], *, sample_size: int,
              rows: List[Dict[str, Any]], limit: int, **extra: Any) -> Dict[str, Any]:
    body = {
        'window_days': days,
        'window_start': bounds['since'].isoformat(),
        'window_end': bounds['until'].isoformat(),
        'sample_size': sample_size,
        'min_attempts': MIN_ATTEMPTS,
        'row_total': len(rows),
        'rows': rows[:limit],
        'scope': scope.describe(),
    }
    body.update(extra)
    return body


def flaky(scope: RunScope, days: int, limit: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    bounds = window(days, now)
    identities = run_quality_db.flaky_identities(
        scope.team_id, scope.host_names, scope.device_keys, bounds['since'], bounds['until'],
        MIN_ATTEMPTS) if scope.host_names else []
    rows = [{
        'identity': _identity(r),
        'attempts': r.get('attempts'),
        'passes': r.get('passes'),
        'failures': r.get('fails'),
        'transitions': r.get('transitions'),
        'flaky_score': float(r['flaky_score']) if r.get('flaky_score') is not None else None,
        'last_status': r.get('last_status') or 'unknown',
        'first_started_at': r.get('first_started_at'),
        'last_started_at': r.get('last_started_at'),
        'latest_script_result_id': str(r['last_result_id']) if r.get('last_result_id') else None,
    } for r in identities if r.get('is_flaky')]
    return _envelope(
        scope, days, bounds, rows=rows, limit=limit,
        sample_size=sum(int(r.get('attempts') or 0) for r in identities),
        identities_evaluated=len(identities),
        metric='adjacent pass/fail transitions / (attempts - 1)',
    )


def slow(scope: RunScope, days: int, limit: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    bounds = window(days, now)
    identities = run_quality_db.slow_identities(
        scope.team_id, scope.host_names, scope.device_keys, bounds['since'], bounds['until'],
        MIN_ATTEMPTS) if scope.host_names else []
    rows = [{
        'identity': _identity(r),
        'sample_count': r.get('samples'),
        'p50_ms': r.get('p50_ms'),
        'p95_ms': r.get('p95_ms'),
        'max_ms': r.get('max_ms'),
        'last_started_at': r.get('last_started_at'),
        'latest_script_result_id': str(r['last_result_id']) if r.get('last_result_id') else None,
    } for r in identities]
    return _envelope(
        scope, days, bounds, rows=rows, limit=limit,
        sample_size=sum(int(r.get('samples') or 0) for r in identities),
        percentile_method='nearest-rank',
    )


def _normalize_name(name: str) -> str:
    name = (name or '').strip()
    return name[:-3] if name.endswith('.py') else name


def runnable_catalog(team_id: str) -> List[Dict[str, Any]]:
    """Scripts and test cases a user of this server can launch now.

    Mirrors what Run Tests offers: the server's discoverable scripts minus the
    team's hidden ones, plus the team's test cases minus hidden ones.
    """
    from backend_server.src.lib.utils.script_utils import list_available_scripts
    from shared.src.lib.database.library_visibility_db import list_hidden_library_keys
    from shared.src.lib.database.testcase_db import list_testcases

    catalog: List[Dict[str, Any]] = []
    hidden_scripts = list_hidden_library_keys(team_id, 'script')
    for name in list_available_scripts():
        if f'{name}.py' in hidden_scripts:
            continue
        catalog.append({'script_name': name, 'script_type': 'script', 'testcase_id': None,
                        'userinterface_name': None, 'environment': None, 'last_executed_at': None})
    hidden_testcases = list_hidden_library_keys(team_id, 'testcase')
    for tc in list_testcases(team_id):
        if tc.get('testcase_id') in hidden_testcases or not tc.get('testcase_name'):
            continue
        catalog.append({'script_name': tc['testcase_name'], 'script_type': 'testcase',
                        'testcase_id': str(tc['testcase_id']),
                        'userinterface_name': tc.get('userinterface_name'),
                        'environment': tc.get('environment'), 'last_executed_at': None})
    return catalog


def not_executed(scope: RunScope, days: int, limit: int, now: Optional[datetime] = None,
                 catalog: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    bounds = window(days, now)
    if not scope.host_names:
        return _envelope(scope, days, bounds, rows=[], limit=limit, sample_size=0,
                         label='not executed in window', runnable_total=0,
                         note='no registered host in scope: nothing is runnable from this server')
    items = catalog if catalog is not None else runnable_catalog(scope.team_id)
    executed = run_quality_db.executed_script_names(
        scope.team_id, scope.host_names, scope.device_keys, bounds['since'], bounds['until'])
    executed_names = {_normalize_name(r.get('script_name') or '') for r in executed}
    missing = [item for item in items if _normalize_name(item['script_name']) not in executed_names]
    missing.sort(key=lambda item: (item['script_type'], item['script_name'].lower()))
    return _envelope(
        scope, days, bounds, rows=missing, limit=limit,
        sample_size=sum(int(r.get('attempts') or 0) for r in executed),
        label='not executed in window',
        runnable_total=len(items),
    )
