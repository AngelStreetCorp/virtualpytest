"""
Run management routes (TASK-42): run summary, run groups, milestones, labels,
governance assignments, group report and group rerun.

Scope. The global /server/* guard (app.py) authenticates, applies the viewer
write floor and refuses a team_id the caller does not belong to. Each route here
reads the team from the same place the guard validated it
(auth_middleware._requested_team_id) and narrows every script_results /
campaign_executions read and write to this server's registered hosts,
intersected with the workspace ``host_filter`` (JSON array of host names) and
``device_filter`` (JSON array of ``host:device_id`` keys, resolved to the
device display names results store), before any limit, grouping or
aggregation. Opaque ids are re-checked against that scope; an out-of-scope id
is a 404.

Permissions. Reads: ``reports.tests:view`` (the TestReports permission).
Governance writes: ``reports.runs:edit``. Group rerun launches executions:
``execution.run:run_test`` (same as /server/script/execute).

Paths:
  GET   /server/run-management/summary/<script|campaign|group>/<id>
  GET   /server/run-management/results               governance-filtered result page
  GET   /server/run-management/results/labels        labels of up to 200 result ids
  GET   /server/run-groups            POST /server/run-groups
  GET   /server/run-groups/<id>       PATCH /server/run-groups/<id>   (archive: {"archived": true})
  POST  /server/run-groups/<id>/archive | /restore
  POST  /server/milestones/<id>/archive | /restore
  GET   /server/run-groups/<id>/report
  POST  /server/run-groups/<id>/rerun                {mode, idempotency_key}
  GET   /server/milestones            POST /server/milestones
  GET   /server/milestones/<id>       PATCH /server/milestones/<id>
  GET   /server/run-labels            POST /server/run-labels
  PATCH /server/run-labels/<id>       DELETE /server/run-labels/<id> (assignments only)
  GET|PUT /server/script-results/<id>/labels         {label_ids}
  PUT   /server/script-results/<id>/milestone        {milestone_id | null}
  PUT   /server/script-results/<id>/run-group        {run_group_id | null}
  PUT   /server/script-results/batch/assignments     {script_result_ids, milestone_id?, run_group_id?, label_ids?}
  GET|PUT /server/testcase/<id>/labels               {label_ids}
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import _requested_team_id, require_permission
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.route_response import error_response
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.services.analytics.scope import RunScope, ScopeError, derive_status, scope_from_request
from backend_server.src.services.governance import rerun_payload as rerun
from backend_server.src.services.governance import summary as summ
from shared.src.lib.database import run_management_db as rmdb
from shared.src.lib.database.run_management_db import RunManagementError


server_run_management_bp = Blueprint('server_run_management', __name__)
server_run_groups_bp = Blueprint('server_run_groups', __name__, url_prefix='/server/run-groups')
server_milestones_bp = Blueprint('server_milestones', __name__, url_prefix='/server/milestones')
server_run_labels_bp = Blueprint('server_run_labels', __name__, url_prefix='/server/run-labels')

READ_PERMISSION = 'reports.tests:view'
EDIT_PERMISSION = 'reports.runs:edit'
RERUN_PERMISSION = 'execution.run:run_test'

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_ERROR_STATUS = {'not_found': 404, 'conflict': 409, 'invalid': 400, 'limit': 422}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_management_errors(f):
    """Turn RunManagementError into its HTTP status (inside handle_route_exceptions)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except RunManagementError as e:
            return error_response(e.message, _ERROR_STATUS.get(e.code, 400))
    return wrapped


def _team_id() -> str:
    team_id = _requested_team_id()
    if not team_id:
        raise RunManagementError('invalid', 'team_id is required')
    return rmdb.clean_uuid(team_id, 'team_id')


def _body() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RunManagementError('invalid', 'JSON body must be an object')
    return data


def _scope() -> RunScope:
    """Team + this server's registered hosts + the workspace ``host_filter`` /
    ``device_filter`` (same resolution as every run-services route)."""
    try:
        return scope_from_request(_team_id(), get_host_manager().get_all_hosts())
    except ScopeError as e:
        raise RunManagementError('invalid', e.message)


def _scope_kwargs(scope: RunScope) -> Dict[str, Any]:
    return {'host_names': list(scope.host_names),
            'device_keys': list(scope.device_keys) if scope.device_keys is not None else None}


def _scope_echo(scope: RunScope) -> Dict[str, Any]:
    return {'team_id': scope.team_id, 'host_names': list(scope.host_names),
            'device_filter_applied': scope.device_keys is not None}


def _int_arg(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RunManagementError('invalid', f'{name} must be an integer')
    if not minimum <= value <= maximum:
        raise RunManagementError('invalid', f'{name} must be between {minimum} and {maximum}')
    return value


def _page_args() -> Dict[str, int]:
    return {
        'limit': _int_arg('limit', _DEFAULT_LIMIT, minimum=1, maximum=_MAX_LIMIT),
        'offset': _int_arg('offset', 0, minimum=0, maximum=1_000_000),
    }


def _flag(name: str) -> bool:
    return (request.args.get(name) or '').lower() in ('1', 'true', 'yes')


def _actor() -> Optional[str]:
    user_id = getattr(request, 'user_id', None)
    return str(user_id) if user_id else None


def _page(items: List[Dict[str, Any]], total: int, limit: int, offset: int) -> Dict[str, Any]:
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _governance_refs(team_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    milestone = rmdb.get_milestone(team_id, row['milestone_id']) if row.get('milestone_id') else None
    group = rmdb.get_run_group(team_id, row['run_group_id']) if row.get('run_group_id') else None
    return {
        'labels': rmdb.labels_for_entities(team_id, 'script_result', [str(row['id'])]).get(str(row['id']), []),
        'milestone': {k: milestone.get(k) for k in ('id', 'name', 'archived')} if milestone else None,
        'run_group': {k: group.get(k) for k in ('id', 'name', 'archived')} if group else None,
    }


# ===========================================================================
# Summary
# ===========================================================================


@server_run_management_bp.route('/server/run-management/summary/<kind>/<run_id>', methods=['GET'])
@handle_route_exceptions('run_management:summary')
@require_permission(READ_PERMISSION)
@_run_management_errors
def get_summary(kind: str, run_id: str):
    """Typed identity, verdict counts over ALL children, a child page (optionally
    filtered by ``status`` after counting), a zero-filled UTC trend for the same
    scoped identity, evidence links and metadata.

    ``kind=campaign`` takes a campaign_executions.id (an execution, not the
    campaign template). Query: team_id, host_filter, limit, offset, status,
    trend_days (default 30, max 90).
    """
    if kind not in rmdb.RUN_KINDS:
        raise RunManagementError('invalid', f'kind must be one of {list(rmdb.RUN_KINDS)}')
    scope = _scope()
    team_id = scope.team_id
    page = _page_args()
    status_filter = request.args.get('status') or None
    if status_filter is not None and status_filter not in summ.STATUSES:
        raise RunManagementError('invalid', f'status must be one of {list(summ.STATUSES)}')
    days = summ.clamp_trend_days(request.args.get('trend_days', summ.TREND_DEFAULT_DAYS))
    builder = {'script': _script_summary, 'campaign': _campaign_summary, 'group': _group_summary}[kind]
    payload, children = builder(scope, run_id, days)
    payload['counts'] = summ.count_statuses(c['status'] for c in children)
    if status_filter:
        children = [c for c in children if c['status'] == status_filter]
    payload['children'] = summ.paginate(children, page['limit'], page['offset'])
    payload['identity'] = {'kind': kind, 'id': run_id}
    payload['scope'] = _scope_echo(scope)
    payload['generated_at'] = _now_iso()
    return jsonify(payload)


def _script_summary(scope: RunScope, run_id, days):
    """One execution: its verdict is the only child; navigation steps are evidence."""
    team_id = scope.team_id
    row = rmdb.get_script_result_in_scope(team_id, run_id, **_scope_kwargs(scope))
    if not row:
        raise RunManagementError('not_found', 'script result not found in this scope')
    identity = {f: row.get(f) for f in rmdb.IDENTITY_FIELDS}
    window = summ.trend_window(days)
    history = rmdb.fetch_identity_history(team_id, identity, since=window['since'], **_scope_kwargs(scope))
    payload = {
        'title': row.get('script_name'),
        'status': derive_status(row),
        'started_at': row.get('started_at'),
        'completed_at': row.get('completed_at'),
        'execution_time_ms': row.get('execution_time_ms'),
        'trend': summ.trend_series(history, days=days, identity=identity),
        'metadata': {
            'script_type': row.get('script_type'),
            'userinterface_name': row.get('userinterface_name'),
            'environment': row.get('environment'),
            'host_name': row.get('host_name'),
            'device_name': row.get('device_name'),
            'executed_by': None,
            'campaign_name': None,
            'error': row.get('error_msg'),
            'discard': bool(row.get('discard')),
            'checked': bool(row.get('checked')),
            **_governance_refs(team_id, row),
        },
        'evidence': {
            'verdict_source': 'script_results.success',
            'report_url': row.get('html_report_r2_url'),
            'logs_url': row.get('logs_r2_url'),
            'steps': summ.step_evidence(rmdb.fetch_step_evidence(team_id, str(row['id']))),
        },
    }
    return payload, [summ.result_child(row)]


def _campaign_summary(scope: RunScope, run_id, days):
    team_id = scope.team_id
    campaign_scope = {'host_names': list(scope.host_names),
                      'device_keys': (list(scope.campaign_device_keys)
                                      if scope.campaign_device_keys is not None else None)}
    execution = rmdb.get_campaign_execution_in_scope(team_id, run_id, **campaign_scope)
    if not execution:
        raise RunManagementError('not_found', 'campaign execution not found in this scope')
    linked = [str(i) for i in (execution.get('script_result_ids') or []) if i]
    results = rmdb.fetch_script_results_by_ids(team_id, linked, **_scope_kwargs(scope))
    children = summ.campaign_children(execution, results)
    window = summ.trend_window(days)
    history = rmdb.fetch_campaign_history(team_id, execution, since=window['since'], **campaign_scope)
    identity = {f: execution.get(f) for f in ('campaign_name', 'userinterface_name', 'host_name', 'device_name')}
    has_outcomes = isinstance((execution.get('metadata') or {}).get('script_outcomes'), list)
    payload = {
        'title': execution.get('campaign_name'),
        'status': summ.campaign_status(execution),
        'started_at': execution.get('started_at'),
        'completed_at': execution.get('completed_at'),
        'execution_time_ms': execution.get('execution_time_ms'),
        'trend': summ.trend_series(history, days=days, status_of=summ.campaign_status, identity=identity),
        'metadata': {
            'script_type': 'campaign',
            'userinterface_name': execution.get('userinterface_name'),
            'environment': None,
            'host_name': execution.get('host_name'),
            'device_name': execution.get('device_name'),
            'executed_by': execution.get('executed_by'),
            'campaign_name': execution.get('campaign_name'),
            'error': execution.get('error_message'),
            'execution_status': execution.get('status'),
            'planned_scripts': len(execution.get('script_configurations') or []),
            'milestone': None,
            'run_group': None,
            'labels': [],
        },
        'evidence': {
            'verdict_source': 'campaign_executions.status + success',
            'children_source': ('campaign_executions.metadata.script_outcomes' if has_outcomes
                                else 'campaign_executions.script_result_ids'),
            'report_url': execution.get('html_report_r2_url'),
            'logs_url': execution.get('logs_r2_url'),
            'steps': None,
        },
    }
    return payload, children


def _group_rollup(scope: RunScope, group_id):
    group = rmdb.get_run_group(scope.team_id, rmdb.clean_uuid(group_id, 'run group id'))
    if not group:
        raise RunManagementError('not_found', 'run group not found in this team')
    members = rmdb.fetch_script_results_in_scope(scope.team_id, run_group_id=group['id'], **_scope_kwargs(scope))
    merged = rmdb.merge_latest_with_attempts(members)
    return group, members, merged


def _identity_child(entry):
    return summ.result_child(entry['latest'], attempts=entry['attempt_count'],
                             attempt_ids=entry['attempt_ids'], identity=entry['identity'])


def _group_summary(scope: RunScope, run_id, days):
    group, members, merged = _group_rollup(scope, run_id)
    children = [_identity_child(e) for e in merged]
    started = [str(m['started_at']) for m in members if m.get('started_at')]
    completed = [str(m['completed_at']) for m in members if m.get('completed_at')]
    payload = {
        'title': group.get('name'),
        'status': summ.rollup_status([c['status'] for c in children]),
        'started_at': min(started) if started else None,
        'completed_at': max(completed) if completed else None,
        'execution_time_ms': None,
        'attempts': summ.count_statuses(derive_status(m) for m in members),
        'trend': summ.trend_series(members, days=days, identity={'run_group_id': group['id']}),
        'metadata': {
            'description': group.get('description'),
            'archived': group.get('archived'),
            'pinned': group.get('pinned'),
            'color': group.get('color'),
            'merge': 'latest',
            'milestone': None,
            'run_group': {'id': group['id'], 'name': group.get('name')},
            'labels': [],
        },
        'evidence': {
            'verdict_source': 'latest script_results attempt per identity',
            'report_url': None,
            'logs_url': None,
            'steps': None,
        },
    }
    return payload, children


# ===========================================================================
# Governance-filtered result listing
# ===========================================================================


@server_run_management_bp.route('/server/run-management/results', methods=['GET'])
@handle_route_exceptions('run_management:results')
@require_permission(READ_PERMISSION)
@_run_management_errors
def list_results():
    """Results filtered by milestone_id / run_group_id / label_id (scope first,
    then filters, then the page window), each with its labels."""
    scope = _scope()
    team_id = scope.team_id
    page = _page_args()
    filters = {}
    for name in ('milestone_id', 'run_group_id', 'label_id'):
        if request.args.get(name):
            filters[name] = rmdb.clean_uuid(request.args[name], name)
    rows, total = rmdb.list_script_results_in_scope(
        team_id, include_discarded=not _flag('exclude_discarded'), **_scope_kwargs(scope), **filters, **page)
    labels = rmdb.labels_for_entities(team_id, 'script_result', [str(r['id']) for r in rows])
    items = [{**r, 'labels': labels.get(str(r['id']), [])} for r in rows]
    return jsonify(_page(items, total, page['limit'], page['offset']))


@server_run_management_bp.route('/server/run-management/results/labels', methods=['GET'])
@handle_route_exceptions('run_management:results_labels')
@require_permission(READ_PERMISSION)
@_run_management_errors
def results_labels():
    """``ids`` = comma-separated result ids (max 200). Ids outside the scope are omitted."""
    scope = _scope()
    team_id = scope.team_id
    ids = [i for i in (request.args.get('ids') or '').split(',') if i.strip()]
    if not ids or len(ids) > 200:
        raise RunManagementError('invalid', 'ids must list 1..200 script result ids')
    in_scope = rmdb.fetch_script_results_by_ids(team_id, ids, columns='id', **_scope_kwargs(scope))
    return jsonify({'labels': rmdb.labels_for_entities(team_id, 'script_result', list(in_scope))})


# ===========================================================================
# Run groups
# ===========================================================================


@server_run_groups_bp.route('', methods=['GET'])
@handle_route_exceptions('run_management:list_groups')
@require_permission(READ_PERMISSION)
@_run_management_errors
def list_groups():
    team_id = _team_id()
    page = _page_args()
    rows, total = rmdb.list_run_groups(team_id, include_archived=_flag('include_archived'),
                                       pinned_only=_flag('pinned_only'),
                                       search=(request.args.get('q') or '').strip() or None, **page)
    return jsonify(_page(rows, total, page['limit'], page['offset']))


@server_run_groups_bp.route('', methods=['POST'])
@handle_route_exceptions('run_management:create_group')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def create_group():
    team_id = _team_id()
    fields = {k: v for k, v in _body().items() if k not in ('team_id', 'host_filter', 'device_filter')}
    return jsonify(rmdb.create_run_group(team_id, fields, created_by=_actor())), 201


@server_run_groups_bp.route('/<group_id>', methods=['GET'])
@handle_route_exceptions('run_management:get_group')
@require_permission(READ_PERMISSION)
@_run_management_errors
def get_group(group_id: str):
    team_id = _team_id()
    group = rmdb.get_run_group(team_id, rmdb.clean_uuid(group_id, 'run group id'))
    if not group:
        raise RunManagementError('not_found', 'run group not found in this team')
    return jsonify(group)


@server_run_groups_bp.route('/<group_id>', methods=['PATCH'])
@handle_route_exceptions('run_management:update_group')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def update_group(group_id: str):
    """name, description, color, pinned, archived (archive/restore keeps every link)."""
    team_id = _team_id()
    fields = {k: v for k, v in _body().items() if k not in ('team_id', 'host_filter', 'device_filter')}
    return jsonify(rmdb.update_run_group(team_id, rmdb.clean_uuid(group_id, 'run group id'), fields))


@server_run_groups_bp.route('/<group_id>/archive', methods=['POST'])
@handle_route_exceptions('run_management:archive_group')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def archive_group(group_id: str):
    """Same as PATCH {"archived": true}; members keep their link."""
    return jsonify(rmdb.archive_run_group(_team_id(), rmdb.clean_uuid(group_id, 'run group id')))


@server_run_groups_bp.route('/<group_id>/restore', methods=['POST'])
@handle_route_exceptions('run_management:restore_group')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def restore_group(group_id: str):
    return jsonify(rmdb.restore_run_group(_team_id(), rmdb.clean_uuid(group_id, 'run group id')))


@server_run_groups_bp.route('/<group_id>/report', methods=['GET'])
@handle_route_exceptions('run_management:group_report')
@require_permission(READ_PERMISSION)
@_run_management_errors
def group_report(group_id: str):
    """Latest-merge rollup: ``counts`` over the latest attempt of every identity,
    ``attempts_total`` over every linked attempt, one row per identity (all rows;
    bounded by the aggregate cap), what each rerun mode would select, and the
    recent rerun requests."""
    scope = _scope()
    team_id = scope.team_id
    group, members, merged = _group_rollup(scope, group_id)
    rows = [_identity_child(e) for e in merged]
    rerun_all, skipped_all = rerun.select_rerun_targets(members, 'all')
    rerun_failures, skipped_failures = rerun.select_rerun_targets(members, 'failures')
    return jsonify({
        'group': {**group, 'member_count': len(merged), 'attempt_count': len(members)},
        'merge': 'latest',
        'counts': summ.count_statuses(r['status'] for r in rows),
        'attempts_total': len(members),
        'attempts': summ.count_statuses(derive_status(m) for m in members),
        'rows': rows,
        'rerun_preview': {
            'all': {'targets': len(rerun_all), 'skipped': skipped_all},
            'failures': {'targets': len(rerun_failures), 'skipped': skipped_failures},
        },
        'recent_reruns': rmdb.list_rerun_requests(team_id, group['id']),
        'scope': _scope_echo(scope),
        'generated_at': _now_iso(),
    })


def _create_deployment(team_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    from routes.server_deployment_routes import create_deployment_record
    return create_deployment_record(team_id, data)


def _rerun_response(record: Dict[str, Any], *, replayed: bool):
    """``dispatched`` items name the source attempt (script_result_id) and the
    queued one-shot deployment; the new result appears when the host finishes."""
    skipped = record.get('skipped') or []
    body = {
        'request_id': record.get('id'),
        'run_group_id': record.get('run_group_id'),
        'mode': record.get('mode'),
        'status': record.get('status'),
        'idempotent_replay': replayed,
        'dispatched': [{**d, 'script_result_id': d.get('source_script_result_id'), 'task_id': None}
                       for d in (record.get('dispatched') or [])],
        'skipped_manual': [s.get('script_result_id') for s in skipped if s.get('reason') == 'manual_run'],
        'skipped_not_in_mode': [s.get('script_result_id') or s.get('script_name')
                                for s in skipped if s.get('reason') != 'manual_run'],
        'skipped': skipped,
        'error': record.get('error'),
    }
    return jsonify(body), (200 if replayed else 202)


@server_run_groups_bp.route('/<group_id>/rerun', methods=['POST'])
@handle_route_exceptions('run_management:group_rerun')
@require_permission(RERUN_PERMISSION)
@_run_management_errors
def group_rerun(group_id: str):
    """Body: {mode: 'all'|'failures', idempotency_key}. Each selected script is
    queued once as a one-shot deployment; a retry with the same key returns the
    recorded outcome without dispatching again. Manual runs are never replayed."""
    scope = _scope()
    team_id = scope.team_id
    body = _body()
    mode = body.get('mode')
    if mode not in rerun.RERUN_MODES:
        raise RunManagementError('invalid', "mode must be 'all' or 'failures'")
    key = body.get('idempotency_key')
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 120:
        raise RunManagementError('invalid', 'idempotency_key must be a 1..120 character string')
    key = key.strip()
    group = rmdb.get_run_group(team_id, rmdb.clean_uuid(group_id, 'run group id'))
    if not group:
        raise RunManagementError('not_found', 'run group not found in this team')

    record, created = rmdb.claim_rerun_request(team_id, group['id'], key, mode, _actor())
    if not created:
        if str(record.get('run_group_id')) != str(group['id']) or record.get('mode') != mode:
            raise RunManagementError('conflict', 'idempotency_key was already used for a different rerun')
        if record.get('status') == 'dispatching':
            raise RunManagementError('conflict', 'this rerun request is still being dispatched')
        return _rerun_response(record, replayed=True)

    dispatched: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    try:
        members = rmdb.fetch_script_results_in_scope(team_id, run_group_id=group['id'], **_scope_kwargs(scope))
        targets, skipped = rerun.select_rerun_targets(members, mode)
        sources = {str(r['id']): r for r in rmdb.fetch_rerun_sources(
            team_id, [str(t['id']) for t in targets], **_scope_kwargs(scope))}
        for target in targets:
            source = sources.get(str(target['id']), target)
            ref = {'script_result_id': str(target['id']), 'script_name': target.get('script_name'),
                   'host_name': target.get('host_name'), 'device_name': target.get('device_name')}
            payload = rerun.rerun_payload_from_result(source)
            if payload is None:
                skipped.append({**ref, 'reason': 'no_rerun_payload'})
            elif payload.get('type') != 'script':
                skipped.append({**ref, 'reason': 'testcase_rerun_not_dispatchable_from_server'})
            else:
                try:
                    dispatched.append(rerun.dispatch_rerun(team_id, source, payload, _create_deployment))
                except Exception as e:
                    skipped.append({**ref, 'reason': 'dispatch_failed', 'error': str(e)})
    except Exception as e:
        record = rmdb.finish_rerun_request(team_id, record['id'], status='failed',
                                           dispatched=dispatched, skipped=skipped, error=str(e))
        return _rerun_response(record, replayed=False)
    record = rmdb.finish_rerun_request(team_id, record['id'], status='dispatched',
                                       dispatched=dispatched, skipped=skipped)
    return _rerun_response(record, replayed=False)


# ===========================================================================
# Milestones
# ===========================================================================


@server_milestones_bp.route('', methods=['GET'])
@handle_route_exceptions('run_management:list_milestones')
@require_permission(READ_PERMISSION)
@_run_management_errors
def list_milestones():
    team_id = _team_id()
    page = _page_args()
    rows, total = rmdb.list_milestones(team_id, include_archived=_flag('include_archived'),
                                       search=(request.args.get('q') or '').strip() or None, **page)
    return jsonify(_page(rows, total, page['limit'], page['offset']))


@server_milestones_bp.route('', methods=['POST'])
@handle_route_exceptions('run_management:create_milestone')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def create_milestone():
    team_id = _team_id()
    fields = {k: v for k, v in _body().items() if k not in ('team_id', 'host_filter', 'device_filter')}
    return jsonify(rmdb.create_milestone(team_id, fields, created_by=_actor())), 201


@server_milestones_bp.route('/<milestone_id>', methods=['GET'])
@handle_route_exceptions('run_management:get_milestone')
@require_permission(READ_PERMISSION)
@_run_management_errors
def get_milestone(milestone_id: str):
    team_id = _team_id()
    milestone = rmdb.get_milestone(team_id, rmdb.clean_uuid(milestone_id, 'milestone id'))
    if not milestone:
        raise RunManagementError('not_found', 'milestone not found in this team')
    return jsonify(milestone)


@server_milestones_bp.route('/<milestone_id>', methods=['PATCH'])
@handle_route_exceptions('run_management:update_milestone')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def update_milestone(milestone_id: str):
    """name, description, due_at, completed_at (null clears), archived."""
    team_id = _team_id()
    fields = {k: v for k, v in _body().items() if k not in ('team_id', 'host_filter', 'device_filter')}
    return jsonify(rmdb.update_milestone(team_id, rmdb.clean_uuid(milestone_id, 'milestone id'), fields))


@server_milestones_bp.route('/<milestone_id>/archive', methods=['POST'])
@handle_route_exceptions('run_management:archive_milestone')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def archive_milestone(milestone_id: str):
    """Same as PATCH {"archived": true}; linked results keep their link."""
    return jsonify(rmdb.archive_milestone(_team_id(), rmdb.clean_uuid(milestone_id, 'milestone id')))


@server_milestones_bp.route('/<milestone_id>/restore', methods=['POST'])
@handle_route_exceptions('run_management:restore_milestone')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def restore_milestone(milestone_id: str):
    return jsonify(rmdb.restore_milestone(_team_id(), rmdb.clean_uuid(milestone_id, 'milestone id')))


# ===========================================================================
# Labels
# ===========================================================================


@server_run_labels_bp.route('', methods=['GET'])
@handle_route_exceptions('run_management:list_labels')
@require_permission(READ_PERMISSION)
@_run_management_errors
def list_labels():
    team_id = _team_id()
    limit = _int_arg('limit', 200, minimum=1, maximum=500)
    offset = _int_arg('offset', 0, minimum=0, maximum=1_000_000)
    rows, total = rmdb.list_run_labels(team_id, search=(request.args.get('q') or '').strip() or None,
                                       limit=limit, offset=offset)
    return jsonify(_page(rows, total, limit, offset))


@server_run_labels_bp.route('', methods=['POST'])
@handle_route_exceptions('run_management:create_label')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def create_label():
    team_id = _team_id()
    body = _body()
    unknown = set(body) - {'team_id', 'name', 'color'}
    if unknown:
        raise RunManagementError('invalid', f'unknown fields: {sorted(unknown)}')
    label = rmdb.create_run_label(team_id, name=body.get('name'), color=body.get('color'), created_by=_actor())
    return jsonify(label), 201


@server_run_labels_bp.route('/<label_id>', methods=['PATCH'])
@handle_route_exceptions('run_management:update_label')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def update_label(label_id: str):
    """Rename / recolor. Assignments reference the id, so a rename is canonical."""
    team_id = _team_id()
    fields = {k: v for k, v in _body().items() if k != 'team_id'}
    return jsonify(rmdb.update_run_label(team_id, rmdb.clean_uuid(label_id, 'label id'), fields))


@server_run_labels_bp.route('/<label_id>', methods=['DELETE'])
@handle_route_exceptions('run_management:delete_label')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def delete_label(label_id: str):
    """Removes the definition and its assignments; results and testcases are untouched."""
    team_id = _team_id()
    return jsonify(rmdb.delete_run_label(team_id, rmdb.clean_uuid(label_id, 'label id')))


# ===========================================================================
# Assignments
# ===========================================================================


def _result_in_scope_or_404(scope: RunScope, script_result_id: str) -> Dict[str, Any]:
    row = rmdb.get_script_result_in_scope(scope.team_id, script_result_id,
                                          columns='id, host_name, device_name, milestone_id, run_group_id',
                                          **_scope_kwargs(scope))
    if not row:
        raise RunManagementError('not_found', 'script result not found in this scope')
    return row


@server_run_management_bp.route('/server/script-results/<script_result_id>/labels', methods=['GET'])
@handle_route_exceptions('run_management:get_result_labels')
@require_permission(READ_PERMISSION)
@_run_management_errors
def get_result_labels(script_result_id: str):
    scope = _scope()
    team_id = scope.team_id
    row = _result_in_scope_or_404(scope, script_result_id)
    labels = rmdb.labels_for_entities(team_id, 'script_result', [str(row['id'])])
    return jsonify({'script_result_id': str(row['id']), 'labels': labels.get(str(row['id']), [])})


@server_run_management_bp.route('/server/script-results/<script_result_id>/labels', methods=['PUT'])
@handle_route_exceptions('run_management:set_result_labels')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def set_result_labels(script_result_id: str):
    """Body {label_ids: [...]} replaces the whole set atomically (max 10, same team)."""
    scope = _scope()
    team_id = scope.team_id
    body = _body()
    if 'label_ids' not in body:
        raise RunManagementError('invalid', 'label_ids is required')
    sid = rmdb.clean_uuid(script_result_id, 'script result id')
    rmdb.replace_labels(team_id, 'script_result', sid, body['label_ids'], actor=_actor(),
                        **_scope_kwargs(scope))
    labels = rmdb.labels_for_entities(team_id, 'script_result', [sid])
    return jsonify({'script_result_id': sid, 'labels': labels.get(sid, [])})


def _single_assignment(script_result_id: str, field: str):
    scope = _scope()
    team_id = scope.team_id
    body = _body()
    if field not in body:
        raise RunManagementError('invalid', f'{field} is required (null clears it)')
    sid = rmdb.clean_uuid(script_result_id, 'script result id')
    rmdb.assign_script_results(team_id, [sid], actor=_actor(), **_scope_kwargs(scope),
                               **{field: body[field]})
    return jsonify({'script_result_id': sid, field: body[field]})


@server_run_management_bp.route('/server/script-results/<script_result_id>/milestone', methods=['PUT'])
@handle_route_exceptions('run_management:set_result_milestone')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def set_result_milestone(script_result_id: str):
    return _single_assignment(script_result_id, 'milestone_id')


@server_run_management_bp.route('/server/script-results/<script_result_id>/run-group', methods=['PUT'])
@handle_route_exceptions('run_management:set_result_run_group')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def set_result_run_group(script_result_id: str):
    return _single_assignment(script_result_id, 'run_group_id')


@server_run_management_bp.route('/server/script-results/batch/assignments', methods=['PUT'])
@handle_route_exceptions('run_management:batch_assign')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def batch_assign():
    """Body {script_result_ids: [...<=500], milestone_id?, run_group_id?, label_ids?}.
    Omitted keys are untouched, null clears. All members are scope-checked and the
    whole batch commits or nothing does."""
    scope = _scope()
    team_id = scope.team_id
    body = _body()
    unknown = set(body) - {'team_id', 'host_filter', 'device_filter', 'script_result_ids', 'milestone_id', 'run_group_id', 'label_ids'}
    if unknown:
        raise RunManagementError('invalid', f'unknown fields: {sorted(unknown)}')
    kwargs = {k: body[k] for k in ('milestone_id', 'run_group_id', 'label_ids') if k in body}
    result = rmdb.assign_script_results(team_id, body.get('script_result_ids'), actor=_actor(),
                                        **_scope_kwargs(scope), **kwargs)
    return jsonify(result)


@server_run_management_bp.route('/server/testcase/<testcase_id>/labels', methods=['GET'])
@handle_route_exceptions('run_management:get_testcase_labels')
@require_permission(READ_PERMISSION)
@_run_management_errors
def get_testcase_labels(testcase_id: str):
    team_id = _team_id()
    testcase = rmdb.get_testcase_in_team(team_id, testcase_id)
    if not testcase:
        raise RunManagementError('not_found', 'testcase not found in this team')
    tid = str(testcase['testcase_id'])
    return jsonify({'testcase_id': tid, 'labels': rmdb.labels_for_entities(team_id, 'testcase', [tid]).get(tid, [])})


@server_run_management_bp.route('/server/testcase/<testcase_id>/labels', methods=['PUT'])
@handle_route_exceptions('run_management:set_testcase_labels')
@require_permission(EDIT_PERMISSION)
@_run_management_errors
def set_testcase_labels(testcase_id: str):
    """Body {label_ids: [...]} replaces the testcase's label set atomically."""
    team_id = _team_id()
    body = _body()
    if 'label_ids' not in body:
        raise RunManagementError('invalid', 'label_ids is required')
    tid = rmdb.clean_uuid(testcase_id, 'testcase id')
    rmdb.replace_labels(team_id, 'testcase', tid, body['label_ids'], host_names=None, actor=_actor())
    labels = rmdb.labels_for_entities(team_id, 'testcase', [tid])
    return jsonify({'testcase_id': tid, 'labels': labels.get(tid, [])})
