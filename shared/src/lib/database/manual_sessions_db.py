"""Manual run sessions (TASK-42).

Creation, step updates and finalization go through SQL functions so each is a
single transaction:

* ``rm_create_manual_session`` — idempotent per ``(team_id, idempotency_key)``;
  inserts the session and its steps together.
* ``rm_update_manual_session`` — optimistic concurrency on ``optimistic_version`` under a
  row lock; raises ``rm:version_conflict`` when the caller's version is stale.
* ``rm_finalize_manual_session`` — row lock + status check, so concurrent or
  repeated finalize calls produce exactly one ``script_results`` row
  (``script_type = 'manual'``) and always return that same id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.src.lib.database.run_rpc import call_rpc, get_supabase, normalize_row

_SESSION_UUID_KEYS = ('id', 'team_id', 'testcase_id', 'script_result_id')
_SESSION_COLUMNS = (
    'id, team_id, actor_id, idempotency_key, testcase_id, testcase_version, testcase_name, '
    'userinterface_name, environment, host_name, device_name, status, optimistic_version, notes, '
    'started_at, updated_at, finalized_at, finalized_by, script_result_id'
)
_STEP_COLUMNS = 'ordinal, label, expected, required, outcome, note, evidence_url, updated_by, updated_at'


def create_session(team_id: str, actor_id: str, *, idempotency_key: str, testcase_id: str,
                   testcase_version: Optional[int], testcase_name: str,
                   testcase_snapshot: Dict[str, Any], userinterface_name: Optional[str],
                   environment: str, host_name: str, device_name: str,
                   steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    return call_rpc('rm_create_manual_session', {
        'p_team_id': team_id,
        'p_actor_id': actor_id,
        'p_idempotency_key': idempotency_key,
        'p_testcase_id': testcase_id,
        'p_testcase_version': testcase_version,
        'p_testcase_name': testcase_name,
        'p_testcase_snapshot': testcase_snapshot,
        'p_userinterface_name': userinterface_name,
        'p_environment': environment,
        'p_host_name': host_name,
        'p_device_name': device_name,
        'p_steps': steps,
    }) or {}


def get_session(team_id: str, session_id: str, *, include_snapshot: bool = False) -> Optional[Dict[str, Any]]:
    columns = _SESSION_COLUMNS + (', testcase_snapshot' if include_snapshot else '')
    result = (get_supabase().table('manual_sessions').select(columns)
              .eq('team_id', team_id).eq('id', session_id).limit(1).execute())
    rows = result.data or []
    if not rows:
        return None
    session = normalize_row(rows[0], _SESSION_UUID_KEYS, ('testcase_snapshot',))
    steps = (get_supabase().table('manual_session_steps').select(_STEP_COLUMNS)
             .eq('team_id', team_id).eq('session_id', session_id)
             .order('ordinal').execute())
    session['steps'] = list(steps.data or [])
    return session


def list_sessions(team_id: str, actor_id: str, *, host_names: List[str],
                  status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    if not host_names:
        return []
    query = (get_supabase().table('manual_sessions').select(_SESSION_COLUMNS)
             .eq('team_id', team_id).eq('actor_id', actor_id)
             .in_('host_name', list(host_names)))
    if status:
        query = query.eq('status', status)
    result = query.order('started_at', desc=True).limit(limit).execute()
    return [normalize_row(r, _SESSION_UUID_KEYS) for r in (result.data or [])]


def update_session(team_id: str, session_id: str, *, expected_version: int, actor_id: str,
                   steps: List[Dict[str, Any]], notes: Optional[str], set_notes: bool,
                   abandon: bool) -> int:
    return int(call_rpc('rm_update_manual_session', {
        'p_team_id': team_id,
        'p_session_id': session_id,
        'p_expected_version': expected_version,
        'p_actor_id': actor_id,
        'p_steps': steps,
        'p_notes': notes,
        'p_set_notes': set_notes,
        'p_abandon': abandon,
    }))


def finalize_session(team_id: str, session_id: str, *, actor_id: str,
                     expected_version: Optional[int]) -> Dict[str, Any]:
    return call_rpc('rm_finalize_manual_session', {
        'p_team_id': team_id,
        'p_session_id': session_id,
        'p_actor_id': actor_id,
        'p_expected_version': expected_version,
    }) or {}
