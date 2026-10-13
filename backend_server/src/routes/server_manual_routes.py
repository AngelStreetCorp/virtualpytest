"""Manual run sessions (TASK-42 §4.2, §9 Manual).

    POST  /server/manual-sessions                {team_id, idempotency_key, testcase_id, host_name,
                                                  device_name, environment?, steps?: [{label, required?}]}
    GET   /server/manual-sessions?team_id=&status=
    GET   /server/manual-sessions/<id>?team_id=
    PATCH /server/manual-sessions/<id>           {team_id, expected_version, steps?: [{ordinal, outcome?,
                                                  note?, evidence_url?}], notes?, abandon?}
    POST  /server/manual-sessions/<id>/finalize  {team_id, expected_version?, idempotency_key?}
          -> {script_result_id, idempotent, session}

Create is idempotent per (team, idempotency_key). PATCH uses optimistic
concurrency: a stale ``expected_version`` answers 409 with the current
session. Finalize is idempotent and produces exactly one ``script_results``
row (``script_type='manual'``) whose id is returned on every repeat call.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics.scope import (
    ScopeError,
    actor_id,
    error_json,
    handle_scope_errors,
    json_body,
    registered_hosts,
    require_uuid,
    resolve_scope,
)
from backend_server.src.services.manual import sessions as manual
from shared.src.lib.database import manual_sessions_db
from shared.src.lib.database.run_rpc import RunDbError

server_manual_bp = Blueprint('server_manual_sessions', __name__, url_prefix='/server/manual-sessions')

_STATUSES = ('in_progress', 'finalized', 'abandoned')
_DB_ERRORS = {
    'not_found': (404, 'manual session not found'),
    'version_conflict': (409, 'the session was changed by someone else; reload and retry'),
    'not_in_progress': (409, 'the session is no longer in progress'),
    'incomplete': (422, 'required steps have no outcome; record or mark them skipped'),
    'bad_step': (400, 'unknown step ordinal'),
}


def _db_error(e: RunDbError, team_id: str, session_id: str):
    status, message = _DB_ERRORS.get(e.code, (500, 'manual session update failed'))
    extra = {'code': e.code}
    if e.detail:
        extra['detail'] = e.detail
    if e.code in ('version_conflict', 'not_in_progress'):
        current = manual_sessions_db.get_session(team_id, session_id)
        if current:
            extra['current'] = manual.present(current, include_snapshot=False)
    return error_json(message, status, **extra)


def _scoped_session(scope, session_id: str, include_snapshot: bool = False):
    session = manual_sessions_db.get_session(scope.team_id, require_uuid(session_id, 'session_id'),
                                             include_snapshot=include_snapshot)
    if not session or not scope.allows_device(session.get('host_name'), session.get('device_name')):
        raise ScopeError('manual session not found', 404)
    return session


@server_manual_bp.route('', methods=['POST'])
@handle_route_exceptions('manual:create')
@require_user_auth
@require_permission('reports.manual:execute')
@handle_scope_errors
def create_session():
    from shared.src.lib.database.testcase_db import get_testcase, get_testcase_versions

    body = json_body()
    hosts = registered_hosts()
    scope = resolve_scope(hosts=hosts)
    actor = actor_id()
    key = body.get('idempotency_key')
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 120:
        return error_json('idempotency_key is required (1..120 characters)', 400)
    testcase_id = require_uuid(body.get('testcase_id'), 'testcase_id')
    manual.validate_target(scope, body.get('host_name'), body.get('device_name'), hosts)
    testcase = get_testcase(testcase_id, scope.team_id)
    versions = get_testcase_versions(testcase_id, scope.team_id, limit=1) if testcase else []
    if not testcase or not versions:
        return error_json('test case not found', 404)
    snapshot = manual.build_snapshot(versions[0])
    environment = body.get('environment') or testcase.get('environment') or 'prod'
    if environment not in manual.ENVIRONMENTS:
        return error_json('environment must be one of dev, test, prod', 400)
    if body.get('steps') is not None:
        steps = manual.steps_from_request(body.get('steps'))
    else:
        steps = manual.steps_from_graph(snapshot.get('graph_json'))
        if not steps:
            return error_json('the test case has no executable steps; send steps explicitly', 400)
    created = manual_sessions_db.create_session(
        scope.team_id, actor, idempotency_key=key.strip(), testcase_id=testcase_id,
        testcase_version=snapshot.get('version_number'), testcase_name=snapshot['testcase_name'],
        testcase_snapshot=snapshot, userinterface_name=snapshot.get('userinterface_name'),
        environment=environment, host_name=body['host_name'], device_name=body['device_name'],
        steps=steps,
    )
    if not created.get('created') and created.get('actor_id') != actor:
        return error_json('idempotency_key already used by another session', 409)
    session = _scoped_session(scope, str(created['id']), include_snapshot=True)
    return jsonify({**manual.present(session, include_snapshot=True),
                    'created': bool(created.get('created'))}), (201 if created.get('created') else 200)


@server_manual_bp.route('', methods=['GET'])
@handle_route_exceptions('manual:list')
@require_user_auth
@require_permission('reports.manual:execute')
@handle_scope_errors
def list_sessions():
    scope = resolve_scope()
    status = request.args.get('status') or None
    if status and status not in _STATUSES:
        return error_json(f'status must be one of {", ".join(_STATUSES)}', 400)
    rows = manual_sessions_db.list_sessions(scope.team_id, actor_id(), host_names=list(scope.host_names),
                                            status=status)
    rows = [r for r in rows if scope.allows_device(r.get('host_name'), r.get('device_name'))]
    return jsonify({'items': rows})


@server_manual_bp.route('/<session_id>', methods=['GET'])
@handle_route_exceptions('manual:get')
@require_user_auth
@require_permission('reports.manual:execute')
@handle_scope_errors
def get_session(session_id: str):
    scope = resolve_scope()
    return jsonify(manual.present(_scoped_session(scope, session_id, include_snapshot=True),
                                  include_snapshot=True))


@server_manual_bp.route('/<session_id>', methods=['PATCH'])
@handle_route_exceptions('manual:update')
@require_user_auth
@require_permission('reports.manual:execute')
@handle_scope_errors
def update_session(session_id: str):
    scope = resolve_scope()
    body = json_body()
    unknown = set(body) - {'team_id', 'expected_version', 'steps', 'notes', 'abandon', 'host_filter', 'device_filter'}
    if unknown:
        return error_json(f'unexpected fields: {", ".join(sorted(unknown))}', 400)
    expected = body.get('expected_version')
    if not isinstance(expected, int) or isinstance(expected, bool):
        return error_json('expected_version (integer) is required', 400)
    session = _scoped_session(scope, session_id)
    actor = actor_id()
    manual.require_actor(session, actor, getattr(request, 'user_role', None))
    updates = manual.step_updates(body.get('steps'))
    notes = body.get('notes')
    if notes is not None and (not isinstance(notes, str) or len(notes) > 5000):
        return error_json('notes must be a string of at most 5000 characters', 400)
    abandon = body.get('abandon', False)
    if not isinstance(abandon, bool):
        return error_json('abandon must be a boolean', 400)
    try:
        manual_sessions_db.update_session(scope.team_id, session['id'], expected_version=expected,
                                          actor_id=actor, steps=updates, notes=notes,
                                          set_notes='notes' in body, abandon=abandon)
    except RunDbError as e:
        return _db_error(e, scope.team_id, session['id'])
    return jsonify(manual.present(_scoped_session(scope, session['id']), include_snapshot=False))


@server_manual_bp.route('/<session_id>/finalize', methods=['POST'])
@handle_route_exceptions('manual:finalize')
@require_user_auth
@require_permission('reports.manual:execute')
@handle_scope_errors
def finalize_session(session_id: str):
    scope = resolve_scope()
    body = json_body()
    expected = body.get('expected_version')
    # Finalize is idempotent per session; a client idempotency_key is accepted but not needed.
    if expected is not None and (not isinstance(expected, int) or isinstance(expected, bool)):
        return error_json('expected_version must be an integer', 400)
    session = _scoped_session(scope, session_id)
    actor = actor_id()
    manual.require_actor(session, actor, getattr(request, 'user_role', None))
    try:
        outcome = manual_sessions_db.finalize_session(scope.team_id, session['id'], actor_id=actor,
                                                      expected_version=expected)
    except RunDbError as e:
        return _db_error(e, scope.team_id, session['id'])
    final = manual.present(_scoped_session(scope, session['id']), include_snapshot=False)
    status = 200 if outcome.get('already_finalized') else 201
    return jsonify({
        'script_result_id': str(outcome.get('script_result_id')),
        'idempotent': bool(outcome.get('already_finalized')),
        'session': final,
    }), status
