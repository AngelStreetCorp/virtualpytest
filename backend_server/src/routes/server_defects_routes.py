"""Test-result defects, evidence links and the explicit Jira push (TASK-42).

    GET    /server/defects?team_id=&status=&severity=&integration=&script_result_id=&limit=&offset=
    POST   /server/defects                      {team_id, title, description?, severity?, assignee?, script_result_ids?}
    GET    /server/defects/<id>?team_id=&evidence_limit=&evidence_offset=
    PATCH  /server/defects/<id>                 {team_id, title?, description?, severity?, status?, assignee?}
    POST   /server/defects/<id>/evidence        {team_id, script_result_id} or {team_id, script_result_ids: [...]}
    DELETE /server/defects/<id>/evidence?team_id=&script_result_id=
    DELETE /server/defects/<id>/evidence/<script_result_id>?team_id=
    POST   /server/defects/<id>/push-jira       {team_id, instance_id?, idempotency_key?}
    POST   /server/defects/<id>/refresh-jira    {team_id}

Push idempotency is per defect (one durable push record per defect); a client
``idempotency_key`` is accepted but not needed.

Defects are team-level objects; evidence links are only created for, listed
for and removed from script results inside the caller's scope (team + this
server's hosts + workspace filter). Changing a defect's status never touches
the linked script results.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics.scope import (
    RunScope,
    ScopeError,
    actor_id,
    bounded_int,
    error_json,
    handle_scope_errors,
    json_body,
    require_uuid,
    resolve_scope,
    resolve_team_id,
)
from backend_server.src.services.defects import jira
from shared.src.lib.database import run_defects_db
from shared.src.lib.database.run_rpc import get_supabase

server_defects_bp = Blueprint('server_defects', __name__, url_prefix='/server/defects')

TITLE_MAX = 200
DESCRIPTION_MAX = 5000
ASSIGNEE_MAX = 200
MAX_EVIDENCE_PER_REQUEST = 100
_PATCHABLE = ('title', 'description', 'severity', 'status', 'assignee')


def _text(raw: Any, name: str, maximum: int, *, required: bool) -> Any:
    if raw is None:
        if required:
            raise ScopeError(f'{name} is required', 400)
        return None
    if not isinstance(raw, str):
        raise ScopeError(f'{name} must be a string', 400)
    value = raw.strip()
    if required and not value:
        raise ScopeError(f'{name} is required', 400)
    if len(value) > maximum:
        raise ScopeError(f'{name} must be at most {maximum} characters', 400)
    return value or None


def _choice(raw: Any, name: str, allowed) -> str:
    if raw not in allowed:
        raise ScopeError(f'{name} must be one of {", ".join(allowed)}', 400)
    return raw


def _result_ids(raw: Any) -> List[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_EVIDENCE_PER_REQUEST:
        raise ScopeError(f'script_result_ids must be a list of at most {MAX_EVIDENCE_PER_REQUEST} ids', 400)
    ids = list(dict.fromkeys(str(i) for i in raw))
    for rid in ids:
        require_uuid(rid, 'script_result_ids[]')
    return ids


def _scoped_result_ids(scope: RunScope, ids: List[str]) -> List[str]:
    """Return ids that are NOT visible in scope (empty list = all visible)."""
    if not ids:
        return []
    if not scope.host_names:
        return ids
    rows = (get_supabase().table('script_results').select('id, team_id, host_name, device_name')
            .eq('team_id', scope.team_id).in_('id', ids).in_('host_name', list(scope.host_names))
            .execute()).data or []
    visible = {str(r['id']) for r in rows if scope.allows_result(r)}
    return [i for i in ids if i not in visible]


def _defect_or_404(team_id: str, defect_id: str):
    defect = run_defects_db.get_defect(team_id, require_uuid(defect_id, 'defect_id'))
    if not defect:
        raise ScopeError('defect not found', 404)
    return defect


def _public_push_state(push: Any) -> Any:
    if not push:
        return None
    return {k: push.get(k) for k in ('state', 'attempts', 'external_key', 'external_url',
                                     'last_error', 'project_key', 'instance_id', 'updated_at')}


@server_defects_bp.route('', methods=['GET'])
@handle_route_exceptions('defects:list')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def list_defects():
    team_id = resolve_team_id()
    status = request.args.get('status') or None
    severity = request.args.get('severity') or None
    integration = request.args.get('integration') or None
    if status:
        _choice(status, 'status', run_defects_db.DEFECT_STATUSES)
    if severity:
        _choice(severity, 'severity', run_defects_db.DEFECT_SEVERITIES)
    if integration:
        _choice(integration, 'integration', run_defects_db.DEFECT_INTEGRATIONS)
    script_result_id = request.args.get('script_result_id') or None
    if script_result_id:
        scope = resolve_scope(team_id)
        if _scoped_result_ids(scope, [require_uuid(script_result_id, 'script_result_id')]):
            return error_json('script result not found', 404)
    limit = bounded_int(request.args.get('limit'), default=50, minimum=1, maximum=200, name='limit')
    offset = bounded_int(request.args.get('offset'), default=0, minimum=0, maximum=100000, name='offset')
    page = run_defects_db.list_defects(team_id, status=status, severity=severity, integration=integration,
                                       script_result_id=script_result_id, limit=limit, offset=offset)
    return jsonify({**page, 'limit': limit, 'offset': offset})


@server_defects_bp.route('', methods=['POST'])
@handle_route_exceptions('defects:create')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def create_defect():
    body = json_body()
    scope = resolve_scope()
    title = _text(body.get('title'), 'title', TITLE_MAX, required=True)
    description = _text(body.get('description'), 'description', DESCRIPTION_MAX, required=False)
    assignee = _text(body.get('assignee'), 'assignee', ASSIGNEE_MAX, required=False)
    severity = _choice(body.get('severity') or 'medium', 'severity', run_defects_db.DEFECT_SEVERITIES)
    evidence = _result_ids(body.get('script_result_ids'))
    invisible = _scoped_result_ids(scope, evidence)
    if invisible:
        return error_json('script results not found', 404, script_result_ids=invisible)
    actor = actor_id()
    defect = run_defects_db.create_defect(scope.team_id, title=title, description=description,
                                          severity=severity, assignee=assignee, created_by=actor)
    if evidence:
        run_defects_db.link_evidence(scope.team_id, defect['id'], evidence, actor)
    return jsonify({**defect, 'linked_script_result_ids': evidence}), 201


@server_defects_bp.route('/<defect_id>', methods=['GET'])
@handle_route_exceptions('defects:get')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def get_defect(defect_id: str):
    scope = resolve_scope()
    defect = _defect_or_404(scope.team_id, defect_id)
    limit = bounded_int(request.args.get('evidence_limit'), default=50, minimum=1, maximum=200, name='evidence_limit')
    offset = bounded_int(request.args.get('evidence_offset'), default=0, minimum=0, maximum=100000, name='evidence_offset')
    evidence = run_defects_db.list_evidence(scope.team_id, defect['id'], scope.host_names, limit, offset)
    items = [r for r in evidence['items'] if scope.allows_device(r.get('host_name'), r.get('device_name'))]
    return jsonify({
        **defect,
        'evidence': {'items': items, 'total': evidence['total'], 'limit': limit, 'offset': offset},
        'jira_push': _public_push_state(run_defects_db.get_jira_push(scope.team_id, defect['id'])),
    })


@server_defects_bp.route('/<defect_id>', methods=['PATCH'])
@handle_route_exceptions('defects:update')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def update_defect(defect_id: str):
    team_id = resolve_team_id()
    body = json_body()
    unknown = set(body) - set(_PATCHABLE) - {'team_id'}
    if unknown:
        return error_json(f'unexpected fields: {", ".join(sorted(unknown))}', 400)
    defect = _defect_or_404(team_id, defect_id)
    changes: Dict[str, Any] = {}
    if 'title' in body:
        changes['title'] = _text(body['title'], 'title', TITLE_MAX, required=True)
    if 'description' in body:
        changes['description'] = _text(body['description'], 'description', DESCRIPTION_MAX, required=False)
    if 'assignee' in body:
        changes['assignee'] = _text(body['assignee'], 'assignee', ASSIGNEE_MAX, required=False)
    if 'severity' in body:
        changes['severity'] = _choice(body['severity'], 'severity', run_defects_db.DEFECT_SEVERITIES)
    if 'status' in body:
        changes['status'] = _choice(body['status'], 'status', run_defects_db.DEFECT_STATUSES)
    if not changes:
        return error_json('nothing to update', 400)
    updated = run_defects_db.update_defect(team_id, defect['id'], changes)
    if not updated:
        return error_json('defect not found', 404)
    return jsonify(updated)


@server_defects_bp.route('/<defect_id>/evidence', methods=['POST'])
@handle_route_exceptions('defects:link_evidence')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def link_evidence(defect_id: str):
    scope = resolve_scope()
    defect = _defect_or_404(scope.team_id, defect_id)
    body = json_body()
    single = body.get('script_result_id')
    ids = _result_ids([single] if single is not None else body.get('script_result_ids'))
    if not ids:
        return error_json('script_result_ids is required', 400)
    invisible = _scoped_result_ids(scope, ids)
    if invisible:
        return error_json('script results not found', 404, script_result_ids=invisible)
    run_defects_db.link_evidence(scope.team_id, defect['id'], ids, actor_id())
    return jsonify({'defect_id': defect['id'], 'linked_script_result_ids': ids}), 201


@server_defects_bp.route('/<defect_id>/evidence', methods=['DELETE'])
@server_defects_bp.route('/<defect_id>/evidence/<script_result_id>', methods=['DELETE'])
@handle_route_exceptions('defects:unlink_evidence')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def unlink_evidence(defect_id: str, script_result_id: str = None):
    scope = resolve_scope()
    defect = _defect_or_404(scope.team_id, defect_id)
    result_id = require_uuid(script_result_id or request.args.get('script_result_id'), 'script_result_id')
    if _scoped_result_ids(scope, [result_id]):
        return error_json('script result not found', 404)
    if not run_defects_db.unlink_evidence(scope.team_id, defect['id'], result_id):
        return error_json('evidence link not found', 404)
    return jsonify({'defect_id': defect['id'], 'unlinked_script_result_id': result_id})


@server_defects_bp.route('/<defect_id>/push-jira', methods=['POST'])
@handle_route_exceptions('defects:push_jira')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def push_jira(defect_id: str):
    scope = resolve_scope()
    defect = _defect_or_404(scope.team_id, defect_id)
    instance_id = json_body().get('instance_id') or None
    if instance_id is not None and not isinstance(instance_id, str):
        return error_json('instance_id must be a string', 400)
    try:
        instance = jira.load_instance(instance_id, scope.team_id)
    except jira.JiraNotAvailable as e:
        return error_json(e.message, e.status)
    evidence = run_defects_db.list_evidence(scope.team_id, defect['id'], scope.host_names, 1, 0)
    outcome = jira.push(scope.team_id, defect, instance, evidence_count=int(evidence.get('total') or 0))
    return jsonify(outcome['body']), outcome['status']


@server_defects_bp.route('/<defect_id>/refresh-jira', methods=['POST'])
@handle_route_exceptions('defects:refresh_jira')
@require_user_auth
@require_permission('reports.defects:edit')
@handle_scope_errors
def refresh_jira(defect_id: str):
    team_id = resolve_team_id()
    defect = _defect_or_404(team_id, defect_id)
    push_state = run_defects_db.get_jira_push(team_id, defect['id'])
    instance = None
    if push_state and push_state.get('instance_id'):
        try:
            instance = jira.load_instance(push_state['instance_id'], team_id)
        except jira.JiraNotAvailable as e:
            return error_json(e.message, e.status)
    outcome = jira.refresh(team_id, defect, push_state, instance)
    if outcome['status'] == 200:
        outcome['body']['defect'] = run_defects_db.get_defect(team_id, defect['id'])
    return jsonify(outcome['body']), outcome['status']
