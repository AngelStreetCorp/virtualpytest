"""
Run Management Database Operations (TASK-42 Wave 1A).

Owns every CRUD surface for the run-governance, run-quality, share, custom-report
and manual-run slices introduced by TASK-42:

  - run_groups, run_milestones, run_label_definitions
  - script_result_labels, testcase_labels
  - script_results milestone_id / run_group_id assignment
  - defects + defect_script_results evidence links
  - run_share_snapshots (sanitized public share, token hash only)
  - custom_reports (private to creator, schema_version INT in filter)
  - manual_sessions + manual_session_steps (resumable, idempotent finalize)

Plus the pure-function quality helpers the Wave 2 API worker calls:

  - pick_latest_per_group, flaky_score, slow_percentiles, never_executed_in_window
  - parse_tql (TQL v1 grammar from TASK-42 §4.4 / handover §Frozen contracts)

CONTRACTS.md compliance:

  - Every query filters by team_id (multi-tenancy boundary).
  - UUIDs auto-converted to strings on the way out.
  - JSONB fields parsed if returned as strings.
  - Same Supabase client as the rest of the platform
    (``shared.src.lib.utils.supabase_utils.get_supabase_client``).

RLS: every new table is RLS-enabled with service_role-only policies (TASK-10
posture). The DB rejects cross-team writes via composite FKs; this module never
trusts caller-side team_id alone.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from shared.src.lib.database.in_filter import chunked_in
from shared.src.lib.utils.supabase_utils import get_supabase_client


# ---------------------------------------------------------------------------
# Supabase client accessor — pattern shared by every module in this folder.
# ---------------------------------------------------------------------------


def get_supabase():
    """Return the lazily-initialised shared Supabase client."""
    return get_supabase_client()


def _json_field(val: Any) -> Any:
    """Parse a JSONB value that came back as a string. Idempotent."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def _stringify_uuids(row: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
    """Coerce each listed UUID-like column to ``str``. Returns the same row."""
    for key in keys:
        val = row.get(key)
        if val is None:
            continue
        row[key] = str(val)
    return row


def _normalize_row(row: Dict[str, Any], uuid_keys: Sequence[str], json_keys: Sequence[str] = ()) -> Dict[str, Any]:
    """Apply the project's UUID + JSONB conventions on a single returned row."""
    _stringify_uuids(row, uuid_keys)
    for key in json_keys:
        if key in row:
            row[key] = _json_field(row.get(key))
    return row


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp, second precision. Single source of truth for DB writes."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# ---------------------------------------------------------------------------
# Constants shared across functions
# ---------------------------------------------------------------------------


LABEL_MAX_PER_ENTITY = 10  # TASK-42 §3 / §4.2 (also enforced by a DB trigger)
SHARE_MAX_TTL_DAYS = 90
SHARE_DEFAULT_TTL_DAYS = 7
MANUAL_STATUSES = ('in_progress', 'finalizing', 'finalized', 'abandoned')
DEFECT_STATUSES = ('open', 'in_progress', 'resolved', 'closed', 'wont_fix')
DEFECT_SEVERITIES = ('low', 'medium', 'high', 'critical')
RUN_KINDS = ('script', 'campaign', 'group')

# Allowed share payload keys — every other key the caller tries to write is dropped.
# TASK-42 §4.3 share allowlist (sanitized, no metadata / evidence / Jira content).
SHARE_ALLOWED_KEYS = frozenset({
    'title', 'counts', 'status', 'safe_labels', 'durations', 'redacted_rows',
})


# ---------------------------------------------------------------------------
# Run governance: errors, scope helpers, groups, milestones, labels,
# assignments, scoped result reads, group rerun requests.
#
# Every function takes team_id and filters on it. Functions that read or write
# script_results also take ``host_names`` — the caller's effective host scope
# (this server's registered hosts, intersected with the workspace host filter)
# — and ``device_keys``, the workspace device filter as ``host:device_name``
# keys (``None`` = no device filter). ``None`` host_names means unscoped and is only for internal callers that already scoped
# the ids; routes always pass a list. Failures raise RunManagementError (or the
# original exception for infrastructure errors) — nothing here turns an error
# into an empty result.
# ---------------------------------------------------------------------------


class RunManagementError(Exception):
    """A request-level failure: ``code`` is not_found | conflict | invalid | limit."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_RPC_ERROR_TOKENS = (
    ('run_mgmt:label_limit', 'limit'),
    ('run_mgmt:not_found', 'not_found'),
    ('run_mgmt:foreign_label', 'invalid'),
    ('run_mgmt:invalid', 'invalid'),
)


def _translate_db_error(exc: Exception, *, conflict_message: str = 'already exists') -> Exception:
    """Map a database exception to RunManagementError; unknown errors pass through."""
    text = str(exc)
    for token, code in _RPC_ERROR_TOKENS:
        if token in text:
            detail = text.split(token, 1)[1].lstrip(': ').split('\n')[0].strip("'\"}, ")
            return RunManagementError(code, detail or token)
    db_code = str(getattr(exc, 'code', '') or '')
    if db_code == '23505' or 'duplicate key value' in text:
        return RunManagementError('conflict', conflict_message)
    if db_code == '23514' or 'violates check constraint' in text:
        return RunManagementError('invalid', 'value rejected by a database check')
    if db_code == '23503' or 'violates foreign key constraint' in text:
        return RunManagementError('conflict', 'still referenced by other rows')
    return exc


_UNSET: Any = object()
_PAGE_BATCH = 1000          # PostgREST max rows per response on this platform
AGGREGATE_ROW_CAP = 10000   # hard bound for in-memory aggregation
NAME_MAX_GROUP = 120
NAME_MAX_LABEL = 20
DESCRIPTION_MAX = 2000
_HEX_COLOR_RE = re.compile(r'^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$')

# Columns a run listing / aggregate needs. Raw metadata is excluded on purpose.
RESULT_COLUMNS = (
    'id, team_id, script_name, script_type, userinterface_name, host_name, device_name, '
    'environment, success, discard, checked, execution_time_ms, started_at, completed_at, '
    'created_at, html_report_r2_url, logs_r2_url, error_msg, milestone_id, run_group_id'
)


def clean_name(raw: Any, max_len: int, what: str = 'name') -> str:
    """Trim a name; raise invalid unless it is 1..max_len characters."""
    if not isinstance(raw, str):
        raise RunManagementError('invalid', f'{what} must be a string')
    cleaned = raw.strip()
    if not 1 <= len(cleaned) <= max_len:
        raise RunManagementError('invalid', f'{what} must be 1..{max_len} characters after trimming')
    return cleaned


def clean_color(raw: Any) -> Optional[str]:
    """``None``/'' clears; otherwise #rgb, #rrggbb or #rrggbbaa (stored lower-case)."""
    if raw is None or raw == '':
        return None
    if not isinstance(raw, str) or not _HEX_COLOR_RE.match(raw.strip().lower()):
        raise RunManagementError('invalid', 'color must be #rgb, #rrggbb or #rrggbbaa')
    return raw.strip().lower()


def clean_description(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise RunManagementError('invalid', 'description must be a string')
    cleaned = raw.strip()
    if len(cleaned) > DESCRIPTION_MAX:
        raise RunManagementError('invalid', f'description must be at most {DESCRIPTION_MAX} characters')
    return cleaned or None


def clean_timestamp(raw: Any, what: str) -> Optional[str]:
    """ISO-8601 timestamp with a timezone (UTC assumed for a bare date), or None."""
    if raw is None or raw == '':
        return None
    if not isinstance(raw, str):
        raise RunManagementError('invalid', f'{what} must be an ISO-8601 string')
    try:
        parsed = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
    except ValueError:
        raise RunManagementError('invalid', f'{what} is not a valid ISO-8601 timestamp')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def clean_uuid(raw: Any, what: str) -> str:
    try:
        return str(uuid.UUID(str(raw)))
    except (ValueError, TypeError, AttributeError):
        raise RunManagementError('invalid', f'{what} must be a UUID')


def _postgrest_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def device_scope_filter(device_keys: Sequence[str]) -> str:
    """PostgREST ``or`` expression matching rows on any ``host:device`` key."""
    clauses = []
    for key in device_keys:
        host, _, device = str(key).partition(':')
        clauses.append(f'and(host_name.eq.{_postgrest_quote(host)},device_name.eq.{_postgrest_quote(device)})')
    return ','.join(clauses)


def _apply_host_scope(query, host_names: Optional[Sequence[str]],
                      device_keys: Optional[Sequence[str]] = None):
    """Host scope, plus the workspace device filter (``host:device_name`` keys)
    when one is active. Both apply inside the query, before limits."""
    if host_names is not None:
        query = query.in_('host_name', list(host_names))
    if device_keys is not None:
        query = query.or_(device_scope_filter(device_keys)) if device_keys else query.in_('host_name', [])
    return query


def _fetch_all(build_query: Callable[[], Any], *, cap: int = AGGREGATE_ROW_CAP) -> List[Dict[str, Any]]:
    """Page through a query in PostgREST-sized batches. Raises ``limit`` past ``cap``.

    ``build_query`` must return a fresh, fully filtered and deterministically
    ordered query each call.
    """
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        batch = build_query().range(offset, offset + _PAGE_BATCH - 1).execute().data or []
        rows.extend(batch)
        if len(rows) > cap:
            raise RunManagementError('limit', f'more than {cap} rows match; narrow the scope')
        if len(batch) < _PAGE_BATCH:
            return rows
        offset += _PAGE_BATCH


def _rpc(name: str, params: Dict[str, Any]) -> Any:
    try:
        return get_supabase().rpc(name, params).execute().data
    except Exception as e:
        raise _translate_db_error(e)


# ---------------------------------------------------------------------------
# run_groups / run_milestones (same shape; archived instead of deleted)
# ---------------------------------------------------------------------------


_GROUP_FIELDS = ('name', 'description', 'color', 'pinned', 'archived')
_MILESTONE_FIELDS = ('name', 'description', 'due_at', 'completed_at', 'archived')


def _clean_governance_fields(table: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    allowed = _GROUP_FIELDS if table == 'run_groups' else _MILESTONE_FIELDS
    unknown = set(fields) - set(allowed)
    if unknown:
        raise RunManagementError('invalid', f'unknown fields: {sorted(unknown)}')
    out: Dict[str, Any] = {}
    for key, value in fields.items():
        if key == 'name':
            out[key] = clean_name(value, NAME_MAX_GROUP)
        elif key == 'description':
            out[key] = clean_description(value)
        elif key == 'color':
            out[key] = clean_color(value)
        elif key in ('pinned', 'archived'):
            if not isinstance(value, bool):
                raise RunManagementError('invalid', f'{key} must be a boolean')
            out[key] = value
        elif key in ('due_at', 'completed_at'):
            out[key] = clean_timestamp(value, key)
    return out


def _create_governance(table: str, team_id: str, fields: Dict[str, Any], created_by: Optional[str]) -> Dict[str, Any]:
    if 'name' not in fields:
        raise RunManagementError('invalid', 'name is required')
    row = _clean_governance_fields(table, fields)
    row.update({'team_id': team_id, 'created_by': created_by})
    try:
        result = get_supabase().table(table).insert(row).execute()
    except Exception as e:
        raise _translate_db_error(e, conflict_message='a {} with this name already exists'.format(
            'group' if table == 'run_groups' else 'milestone'))
    return _normalize_row(result.data[0], ('id', 'team_id'))


def _list_governance(table: str, team_id: str, *, include_archived: bool, search: Optional[str],
                     limit: int, offset: int, pinned_only: bool = False) -> Tuple[List[Dict[str, Any]], int]:
    query = get_supabase().table(table).select('*', count='exact').eq('team_id', team_id)
    if not include_archived:
        query = query.eq('archived', False)
    if pinned_only:
        query = query.eq('pinned', True)
    if search:
        query = query.ilike('name', '%' + search.replace('%', r'\%').replace('_', r'\_') + '%')
    if table == 'run_groups':
        query = query.order('pinned', desc=True)
    else:
        query = query.order('due_at', desc=False)
    result = query.order('name').order('id').range(offset, offset + limit - 1).execute()
    rows = [_normalize_row(r, ('id', 'team_id')) for r in (result.data or [])]
    total = result.count if isinstance(getattr(result, 'count', None), int) else len(rows)
    return rows, total


def _get_governance(table: str, team_id: str, object_id: str) -> Optional[Dict[str, Any]]:
    result = (get_supabase().table(table).select('*')
              .eq('team_id', team_id).eq('id', object_id).limit(1).execute())
    return _normalize_row(result.data[0], ('id', 'team_id')) if result.data else None


def _update_governance(table: str, team_id: str, object_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    payload = _clean_governance_fields(table, fields)
    if not payload:
        raise RunManagementError('invalid', 'nothing to update')
    try:
        result = (get_supabase().table(table).update(payload)
                  .eq('team_id', team_id).eq('id', object_id).execute())
    except Exception as e:
        raise _translate_db_error(e, conflict_message='another object of this team already has this name')
    if not result.data:
        raise RunManagementError('not_found', 'not found in this team')
    return _normalize_row(result.data[0], ('id', 'team_id'))


def create_run_group(team_id: str, fields: Dict[str, Any], *, created_by: Optional[str] = None) -> Dict[str, Any]:
    return _create_governance('run_groups', team_id, fields, created_by)


def list_run_groups(team_id: str, *, include_archived: bool = False, pinned_only: bool = False,
                    search: Optional[str] = None, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Groups of a team, pinned first then by name. Returns (page, total)."""
    return _list_governance('run_groups', team_id, include_archived=include_archived, search=search,
                            limit=limit, offset=offset, pinned_only=pinned_only)


def get_run_group(team_id: str, run_group_id: str) -> Optional[Dict[str, Any]]:
    return _get_governance('run_groups', team_id, run_group_id)


def update_run_group(team_id: str, run_group_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Patch name/description/color/pinned/archived. Archive keeps every link."""
    return _update_governance('run_groups', team_id, run_group_id, fields)


def archive_run_group(team_id: str, run_group_id: str) -> Dict[str, Any]:
    return update_run_group(team_id, run_group_id, {'archived': True})


def restore_run_group(team_id: str, run_group_id: str) -> Dict[str, Any]:
    return update_run_group(team_id, run_group_id, {'archived': False})


def create_milestone(team_id: str, fields: Dict[str, Any], *, created_by: Optional[str] = None) -> Dict[str, Any]:
    return _create_governance('run_milestones', team_id, fields, created_by)


def list_milestones(team_id: str, *, include_archived: bool = False, search: Optional[str] = None,
                    limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Milestones of a team by due date then name. Returns (page, total)."""
    return _list_governance('run_milestones', team_id, include_archived=include_archived, search=search,
                            limit=limit, offset=offset)


def get_milestone(team_id: str, milestone_id: str) -> Optional[Dict[str, Any]]:
    return _get_governance('run_milestones', team_id, milestone_id)


def update_milestone(team_id: str, milestone_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Patch name/description/due_at/completed_at/archived (null clears a date)."""
    return _update_governance('run_milestones', team_id, milestone_id, fields)


def archive_milestone(team_id: str, milestone_id: str) -> Dict[str, Any]:
    return update_milestone(team_id, milestone_id, {'archived': True})


def restore_milestone(team_id: str, milestone_id: str) -> Dict[str, Any]:
    return update_milestone(team_id, milestone_id, {'archived': False})


# ---------------------------------------------------------------------------
# run_label_definitions
# ---------------------------------------------------------------------------


def create_run_label(team_id: str, *, name: Any, color: Any = None,
                     created_by: Optional[str] = None) -> Dict[str, Any]:
    """Create a team label: trimmed 1..20 chars, unique per team ignoring case."""
    row = {
        'team_id': team_id,
        'name': clean_name(name, NAME_MAX_LABEL),
        'color': clean_color(color),
        'created_by': created_by,
    }
    try:
        result = get_supabase().table('run_label_definitions').insert(row).execute()
    except Exception as e:
        raise _translate_db_error(e, conflict_message='a label with this name already exists (case-insensitive)')
    return _normalize_row(result.data[0], ('id', 'team_id'))


def list_run_labels(team_id: str, *, search: Optional[str] = None, limit: int = 200,
                    offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    query = get_supabase().table('run_label_definitions').select('*', count='exact').eq('team_id', team_id)
    if search:
        query = query.ilike('name', '%' + search.replace('%', r'\%').replace('_', r'\_') + '%')
    result = query.order('name').order('id').range(offset, offset + limit - 1).execute()
    rows = [_normalize_row(r, ('id', 'team_id')) for r in (result.data or [])]
    total = result.count if isinstance(getattr(result, 'count', None), int) else len(rows)
    return rows, total


def update_run_label(team_id: str, label_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Rename and/or recolor. Assignments hold the id, so a rename is canonical."""
    unknown = set(fields) - {'name', 'color'}
    if unknown:
        raise RunManagementError('invalid', f'unknown fields: {sorted(unknown)}')
    payload: Dict[str, Any] = {}
    if 'name' in fields:
        payload['name'] = clean_name(fields['name'], NAME_MAX_LABEL)
    if 'color' in fields:
        payload['color'] = clean_color(fields['color'])
    if not payload:
        raise RunManagementError('invalid', 'nothing to update')
    try:
        result = (get_supabase().table('run_label_definitions').update(payload)
                  .eq('team_id', team_id).eq('id', label_id).execute())
    except Exception as e:
        raise _translate_db_error(e, conflict_message='a label with this name already exists (case-insensitive)')
    if not result.data:
        raise RunManagementError('not_found', 'label not found in this team')
    return _normalize_row(result.data[0], ('id', 'team_id'))


def delete_run_label(team_id: str, label_id: str) -> Dict[str, Any]:
    """Delete a label definition. Its assignments go with it (FK cascade on the
    join rows only); no script result or testcase is touched."""
    sb = get_supabase()
    results = (sb.table('script_result_labels').select('run_label_id', count='exact')
               .eq('team_id', team_id).eq('run_label_id', label_id).limit(1).execute())
    testcases = (sb.table('testcase_labels').select('run_label_id', count='exact')
                 .eq('team_id', team_id).eq('run_label_id', label_id).limit(1).execute())
    deleted = (sb.table('run_label_definitions').delete()
               .eq('team_id', team_id).eq('id', label_id).execute())
    if not deleted.data:
        raise RunManagementError('not_found', 'label not found in this team')
    return {
        'id': label_id,
        'deleted': True,
        'removed_script_result_assignments': results.count or 0,
        'removed_testcase_assignments': testcases.count or 0,
    }


# ---------------------------------------------------------------------------
# Assignments (atomic, via the run_mgmt_* RPCs in 061_run_management.sql)
# ---------------------------------------------------------------------------


def _clean_label_ids(label_ids: Any) -> List[str]:
    if not isinstance(label_ids, list):
        raise RunManagementError('invalid', 'label_ids must be a list')
    cleaned = sorted({clean_uuid(lid, 'label id') for lid in label_ids})
    if len(cleaned) > LABEL_MAX_PER_ENTITY:
        raise RunManagementError('limit', f'at most {LABEL_MAX_PER_ENTITY} labels per entity')
    return cleaned


def replace_labels(team_id: str, entity_kind: str, entity_id: str, label_ids: Any, *,
                   host_names: Optional[Sequence[str]],
                   device_keys: Optional[Sequence[str]] = None, actor: Optional[str] = None) -> Dict[str, Any]:
    """Replace the label set of one script_result or testcase in one transaction.

    The RPC checks the entity is in the team (and, for a script result, in
    ``host_names``), that every label belongs to the team, and the 10 cap.
    """
    if entity_kind not in ('script_result', 'testcase'):
        raise RunManagementError('invalid', 'entity kind must be script_result or testcase')
    data = _rpc('run_mgmt_replace_labels', {
        'p_team_id': team_id,
        'p_entity_kind': entity_kind,
        'p_entity_id': clean_uuid(entity_id, f'{entity_kind} id'),
        'p_label_ids': _clean_label_ids(label_ids),
        'p_host_names': list(host_names) if host_names is not None else None,
        'p_actor': actor,
        'p_device_keys': list(device_keys) if device_keys is not None else None,
    })
    return data if isinstance(data, dict) else {'entity_kind': entity_kind, 'entity_id': entity_id}


def assign_script_results(team_id: str, script_result_ids: Any, *, host_names: Optional[Sequence[str]],
                          device_keys: Optional[Sequence[str]] = None,
                          milestone_id: Any = _UNSET, run_group_id: Any = _UNSET, label_ids: Any = _UNSET,
                          actor: Optional[str] = None) -> Dict[str, Any]:
    """Set milestone and/or group and/or label set on many results, all or nothing.

    Omitted arguments are left untouched; ``None`` clears a milestone/group.
    """
    if not isinstance(script_result_ids, list) or not script_result_ids:
        raise RunManagementError('invalid', 'script_result_ids must be a non-empty list')
    if len(script_result_ids) > 500:
        raise RunManagementError('limit', 'at most 500 script results per batch')
    ids = sorted({clean_uuid(sid, 'script result id') for sid in script_result_ids})
    set_milestone = milestone_id is not _UNSET
    set_group = run_group_id is not _UNSET
    set_labels = label_ids is not _UNSET
    if not (set_milestone or set_group or set_labels):
        raise RunManagementError('invalid', 'nothing to assign: give milestone_id, run_group_id or label_ids')
    data = _rpc('run_mgmt_assign_script_results', {
        'p_team_id': team_id,
        'p_script_result_ids': ids,
        'p_host_names': list(host_names) if host_names is not None else None,
        'p_set_milestone': set_milestone,
        'p_milestone_id': clean_uuid(milestone_id, 'milestone_id') if set_milestone and milestone_id is not None else None,
        'p_set_run_group': set_group,
        'p_run_group_id': clean_uuid(run_group_id, 'run_group_id') if set_group and run_group_id is not None else None,
        'p_set_labels': set_labels,
        'p_label_ids': _clean_label_ids(label_ids) if set_labels else None,
        'p_actor': actor,
        'p_device_keys': list(device_keys) if device_keys is not None else None,
    })
    return data if isinstance(data, dict) else {'script_result_ids': ids, 'updated': len(ids)}


def labels_for_entities(team_id: str, entity_kind: str, entity_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """{entity_id: [label definition, ...]} for already scope-checked ids."""
    out: Dict[str, List[Dict[str, Any]]] = {str(e): [] for e in entity_ids}
    if not entity_ids:
        return out
    table, column = (('script_result_labels', 'script_result_id') if entity_kind == 'script_result'
                     else ('testcase_labels', 'testcase_id'))
    sb = get_supabase()
    rows = chunked_in(
        lambda chunk: sb.table(table)
        .select(f'{column}, run_label_definitions(id, name, color)')
        .eq('team_id', team_id).in_(column, chunk),
        list(out))
    for row in rows:
        label = row.get('run_label_definitions')
        if isinstance(label, list):
            label = label[0] if label else None
        if label:
            out.setdefault(str(row.get(column)), []).append(_normalize_row(dict(label), ('id',)))
    for labels in out.values():
        labels.sort(key=lambda d: (str(d.get('name') or '').lower(), str(d.get('id'))))
    return out


# ---------------------------------------------------------------------------
# Scoped reads of execution records (script_results, campaign_executions,
# execution_results). Read-only: governance never rewrites history.
# ---------------------------------------------------------------------------


def get_script_result_in_scope(team_id: str, script_result_id: str, *, host_names: Optional[Sequence[str]],
                               device_keys: Optional[Sequence[str]] = None,
                               columns: str = RESULT_COLUMNS) -> Optional[Dict[str, Any]]:
    """One result, only if it is in the team AND the host scope."""
    try:
        sid = clean_uuid(script_result_id, 'script result id')
    except RunManagementError:
        return None
    query = get_supabase().table('script_results').select(columns).eq('team_id', team_id).eq('id', sid)
    result = _apply_host_scope(query, host_names, device_keys).limit(1).execute()
    return result.data[0] if result.data else None


def get_testcase_in_team(team_id: str, testcase_id: str) -> Optional[Dict[str, Any]]:
    try:
        tid = clean_uuid(testcase_id, 'testcase id')
    except RunManagementError:
        return None
    result = (get_supabase().table('testcase_definitions')
              .select('testcase_id, team_id, testcase_name, userinterface_name, environment')
              .eq('team_id', team_id).eq('testcase_id', tid).limit(1).execute())
    return result.data[0] if result.data else None


def _results_query(team_id: str, *, host_names: Optional[Sequence[str]],
                   device_keys: Optional[Sequence[str]] = None, milestone_id: Optional[str],
                   run_group_id: Optional[str], label_id: Optional[str], include_discarded: bool,
                   since: Optional[str], columns: str, count: bool):
    select = columns
    if label_id:
        select = f'{columns}, script_result_labels!inner(run_label_id)'
    query = (get_supabase().table('script_results').select(select, count='exact') if count
             else get_supabase().table('script_results').select(select))
    query = _apply_host_scope(query.eq('team_id', team_id), host_names, device_keys)
    if milestone_id:
        query = query.eq('milestone_id', milestone_id)
    if run_group_id:
        query = query.eq('run_group_id', run_group_id)
    if label_id:
        query = query.eq('script_result_labels.run_label_id', label_id)
    if not include_discarded:
        query = query.eq('discard', False)
    if since:
        query = query.gte('started_at', since)
    return query.order('started_at', desc=True).order('id', desc=True)


def _strip_embeds(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for row in rows:
        row.pop('script_result_labels', None)
    return rows


def list_script_results_in_scope(team_id: str, *, host_names: Optional[Sequence[str]],
                                 device_keys: Optional[Sequence[str]] = None,
                                 milestone_id: Optional[str] = None, run_group_id: Optional[str] = None,
                                 label_id: Optional[str] = None, include_discarded: bool = True,
                                 limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """A page of results filtered by governance links, newest first. Scope and
    filters apply before the page window. Returns (page, total)."""
    result = _results_query(team_id, host_names=host_names, device_keys=device_keys, milestone_id=milestone_id,
                            run_group_id=run_group_id, label_id=label_id,
                            include_discarded=include_discarded, since=None,
                            columns=RESULT_COLUMNS, count=True).range(offset, offset + limit - 1).execute()
    rows = _strip_embeds(list(result.data or []))
    total = result.count if isinstance(getattr(result, 'count', None), int) else len(rows)
    return rows, total


def fetch_script_results_in_scope(team_id: str, *, host_names: Optional[Sequence[str]],
                                  device_keys: Optional[Sequence[str]] = None,
                                  milestone_id: Optional[str] = None, run_group_id: Optional[str] = None,
                                  include_discarded: bool = True, since: Optional[str] = None,
                                  columns: str = RESULT_COLUMNS) -> List[Dict[str, Any]]:
    """Every matching result (bounded by AGGREGATE_ROW_CAP) for aggregation."""
    return _strip_embeds(_fetch_all(lambda: _results_query(
        team_id, host_names=host_names, device_keys=device_keys, milestone_id=milestone_id,
        run_group_id=run_group_id, label_id=None, include_discarded=include_discarded, since=since, columns=columns, count=False)))


def fetch_script_results_by_ids(team_id: str, ids: Sequence[str], *, host_names: Optional[Sequence[str]],
                                device_keys: Optional[Sequence[str]] = None,
                                columns: str = RESULT_COLUMNS) -> Dict[str, Dict[str, Any]]:
    """{id: row} for the ids that are in the team and the host scope."""
    out: Dict[str, Dict[str, Any]] = {}
    clean_ids = []
    for raw in ids:
        try:
            clean_ids.append(clean_uuid(raw, 'script result id'))
        except RunManagementError:
            continue
    sb = get_supabase()
    for row in chunked_in(
            lambda chunk: _apply_host_scope(sb.table('script_results').select(columns)
                                            .eq('team_id', team_id).in_('id', chunk), host_names, device_keys),
            clean_ids):
        out[str(row['id'])] = row
    return out


def fetch_identity_history(team_id: str, identity: Dict[str, Any], *, host_names: Optional[Sequence[str]],
                           device_keys: Optional[Sequence[str]] = None,
                           since: str) -> List[Dict[str, Any]]:
    """Attempts of one logical script identity since ``since`` (trend input)."""
    def build():
        query = (get_supabase().table('script_results')
                 .select('id, started_at, success, execution_time_ms, discard')
                 .eq('team_id', team_id).eq('script_name', identity.get('script_name')))
        for column in ('userinterface_name', 'environment', 'host_name', 'device_name'):
            value = identity.get(column)
            query = query.is_(column, 'null') if value is None else query.eq(column, value)
        query = _apply_host_scope(query, host_names, device_keys).gte('started_at', since)
        return query.order('started_at', desc=False).order('id', desc=False)
    return _fetch_all(build)


CAMPAIGN_COLUMNS = (
    'id, team_id, campaign_name, campaign_execution_id, userinterface_name, host_name, device_name, '
    'status, started_at, completed_at, execution_time_ms, success, error_message, executed_by, '
    'script_configurations, script_result_ids, metadata, html_report_r2_url, logs_r2_url'
)


def get_campaign_execution_in_scope(team_id: str, campaign_execution_id: str, *,
                                    host_names: Optional[Sequence[str]],
                                    device_keys: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
    """One campaign execution (campaign_executions.id) in team + host scope."""
    try:
        cid = clean_uuid(campaign_execution_id, 'campaign execution id')
    except RunManagementError:
        return None
    query = (get_supabase().table('campaign_executions').select(CAMPAIGN_COLUMNS)
             .eq('team_id', team_id).eq('id', cid))
    result = _apply_host_scope(query, host_names, device_keys).limit(1).execute()
    if not result.data:
        return None
    row = result.data[0]
    for key in ('script_configurations', 'metadata'):
        row[key] = _json_field(row.get(key))
    return row


def fetch_campaign_history(team_id: str, execution: Dict[str, Any], *, host_names: Optional[Sequence[str]],
                           device_keys: Optional[Sequence[str]] = None,
                           since: str) -> List[Dict[str, Any]]:
    """Executions of the same campaign on the same target since ``since``."""
    def build():
        query = (get_supabase().table('campaign_executions')
                 .select('id, started_at, status, success')
                 .eq('team_id', team_id).eq('campaign_name', execution.get('campaign_name')))
        for column in ('userinterface_name', 'host_name', 'device_name'):
            value = execution.get(column)
            query = query.is_(column, 'null') if value is None else query.eq(column, value)
        query = _apply_host_scope(query, host_names, device_keys).gte('started_at', since)
        return query.order('started_at', desc=False).order('id', desc=False)
    return _fetch_all(build)


def fetch_step_evidence(team_id: str, script_result_id: str) -> List[Dict[str, Any]]:
    """execution_results rows (navigation/action/verification steps) recorded for
    one script result. Only call after the result itself passed the scope check."""
    def build():
        return (get_supabase().table('execution_results')
                .select('id, execution_type, success, executed_at')
                .eq('team_id', team_id).eq('script_result_id', script_result_id)
                .order('executed_at', desc=False).order('id', desc=False))
    return _fetch_all(build, cap=5000)


def fetch_rerun_sources(team_id: str, ids: Sequence[str], *, host_names: Optional[Sequence[str]],
                        device_keys: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Rows with the launch config a rerun needs: metadata plus the deployment
    rerun_payload embedded the same way get_script_results does."""
    columns = (RESULT_COLUMNS + ', metadata, deployment_executions(deployments(rerun_payload))')
    rows = list(fetch_script_results_by_ids(team_id, ids, host_names=host_names, device_keys=device_keys,
                                            columns=columns).values())
    for row in rows:
        row['metadata'] = _json_field(row.get('metadata'))
        executions = row.pop('deployment_executions', None)
        if isinstance(executions, dict):
            executions = [executions]
        payload = None
        for execution in executions or []:
            deployment = (execution or {}).get('deployments')
            if isinstance(deployment, list):
                deployment = deployment[0] if deployment else None
            if (deployment or {}).get('rerun_payload'):
                payload = _json_field(deployment['rerun_payload'])
                break
        row['rerun_payload'] = payload
    return rows


# ---------------------------------------------------------------------------
# Group merge (latest attempt per logical identity, all attempts kept)
# ---------------------------------------------------------------------------


IDENTITY_FIELDS = ('script_name', 'userinterface_name', 'environment', 'host_name', 'device_name')


def identity_of(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row.get(f) for f in IDENTITY_FIELDS)


def merge_latest_with_attempts(members: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per identity: the latest attempt (started_at, then id) plus the
    attempt count and every attempt id, newest first. Attempts are not modified."""
    attempts: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for member in members or []:
        attempts.setdefault(identity_of(member), []).append(member)
    merged = []
    for latest in pick_latest_per_group(members):
        history = sorted(attempts[identity_of(latest)],
                         key=lambda m: (str(m.get('started_at') or ''), str(m.get('id') or '')), reverse=True)
        merged.append({
            'identity': dict(zip(IDENTITY_FIELDS, identity_of(latest))),
            'latest': latest,
            'attempt_count': len(history),
            'attempt_ids': [str(m.get('id')) for m in history],
        })
    return merged


# ---------------------------------------------------------------------------
# run_group_rerun_requests (durable idempotency)
# ---------------------------------------------------------------------------


def claim_rerun_request(team_id: str, run_group_id: str, idempotency_key: str, mode: str,
                        requested_by: Optional[str]) -> Tuple[Dict[str, Any], bool]:
    """Insert the request row. Returns (row, True) for a new key, or the existing
    row and False when the key was already used by this team."""
    row = {
        'team_id': team_id,
        'run_group_id': run_group_id,
        'idempotency_key': idempotency_key,
        'mode': mode,
        'status': 'dispatching',
        'requested_by': requested_by,
    }
    try:
        result = get_supabase().table('run_group_rerun_requests').insert(row).execute()
        return _normalize_row(result.data[0], ('id', 'team_id', 'run_group_id')), True
    except Exception as e:
        translated = _translate_db_error(e)
        if not (isinstance(translated, RunManagementError) and translated.code == 'conflict'):
            raise translated
    existing = (get_supabase().table('run_group_rerun_requests').select('*')
                .eq('team_id', team_id).eq('idempotency_key', idempotency_key).limit(1).execute())
    if not existing.data:
        raise RunManagementError('conflict', 'idempotency key collision could not be resolved')
    return _normalize_row(existing.data[0], ('id', 'team_id', 'run_group_id')), False


def finish_rerun_request(team_id: str, request_id: str, *, status: str, dispatched: List[Dict[str, Any]],
                         skipped: List[Dict[str, Any]], error: Optional[str] = None) -> Dict[str, Any]:
    result = (get_supabase().table('run_group_rerun_requests').update({
        'status': status,
        'dispatched': dispatched,
        'skipped': skipped,
        'error': error,
        'completed_at': _utc_now_iso(),
    }).eq('team_id', team_id).eq('id', request_id).execute())
    if not result.data:
        raise RunManagementError('not_found', 'rerun request vanished while dispatching')
    return _normalize_row(result.data[0], ('id', 'team_id', 'run_group_id'))


def list_rerun_requests(team_id: str, run_group_id: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    result = (get_supabase().table('run_group_rerun_requests')
              .select('id, mode, status, requested_by, created_at, completed_at, dispatched, skipped, error')
              .eq('team_id', team_id).eq('run_group_id', run_group_id)
              .order('created_at', desc=True).limit(limit).execute())
    return [_normalize_row(r, ('id',)) for r in (result.data or [])]


# ---------------------------------------------------------------------------
# Quality / analytics helpers — pure functions the API worker can call directly
# ---------------------------------------------------------------------------


def pick_latest_per_group(members: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """v1 group merge (TASK-42 §3 handover): for each logical-script identity
    (script + UI + env + host + device) keep the most recent attempt.

    Key tuple: ``(script_name, userinterface_name, environment, host_name, device_name)``.
    Order: ``(started_at DESC, id DESC)``.

    Returns the kept members sorted newest-first.
    """
    by_key: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for member in members or []:
        key = (
            member.get('script_name'),
            member.get('userinterface_name'),
            member.get('environment'),
            member.get('host_name'),
            member.get('device_name'),
        )
        prev = by_key.get(key)
        if not prev:
            by_key[key] = member
            continue
        prev_sort = (prev.get('started_at') or '', prev.get('id') or '')
        cur_sort = (member.get('started_at') or '', member.get('id') or '')
        if cur_sort > prev_sort:
            by_key[key] = member
    return sorted(by_key.values(), key=lambda m: (m.get('started_at') or '', m.get('id') or ''), reverse=True)


__all__ = [
    # run governance
    'RunManagementError', 'clean_name', 'clean_color', 'clean_description', 'clean_timestamp', 'clean_uuid',
    'create_run_group', 'list_run_groups', 'get_run_group',
    'update_run_group', 'archive_run_group', 'restore_run_group',
    'create_milestone', 'list_milestones', 'get_milestone',
    'update_milestone', 'archive_milestone', 'restore_milestone',
    'create_run_label', 'list_run_labels', 'update_run_label', 'delete_run_label',
    'replace_labels', 'assign_script_results', 'labels_for_entities',
    'get_script_result_in_scope', 'get_testcase_in_team', 'list_script_results_in_scope',
    'fetch_script_results_in_scope', 'fetch_script_results_by_ids', 'fetch_identity_history',
    'get_campaign_execution_in_scope', 'fetch_campaign_history', 'fetch_step_evidence',
    'fetch_rerun_sources', 'IDENTITY_FIELDS', 'identity_of', 'merge_latest_with_attempts',
    'claim_rerun_request', 'finish_rerun_request', 'list_rerun_requests',
    # analytics helpers
    'pick_latest_per_group',
    'LABEL_MAX_PER_ENTITY',
]