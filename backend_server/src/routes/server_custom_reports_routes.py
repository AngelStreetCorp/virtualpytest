"""Saved custom reports, private to their creator within a team (TASK-42).

    GET    /server/custom-reports?team_id=
    POST   /server/custom-reports                 {team_id, name, filter{schema_version, tql}, columns, chart{type, group_by?},
                                                    sort?, order?, include_discarded?}
    GET    /server/custom-reports/<id>?team_id=
    PATCH  /server/custom-reports/<id>            {team_id, name?, filter?, columns?, chart?, sort?, order?, include_discarded?}
    DELETE /server/custom-reports/<id>?team_id=

The definition fields are validated by
``services/analytics/report_query.validate_definition`` (the filter is
versioned by ``schema_version``) on save and again on every load: a report
whose stored definition no longer validates is returned with ``valid: false``
and the reason, never silently "fixed". Execution (``POST
/server/run-management/query``) validates once more, including label and
milestone names. Every operation filters on team_id AND the caller as creator.
"""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics import report_query
from backend_server.src.services.analytics.scope import (
    ScopeError,
    actor_id,
    error_json,
    handle_scope_errors,
    json_body,
    require_uuid,
    resolve_team_id,
)
from shared.src.lib.database import custom_reports_db

server_custom_reports_bp = Blueprint('server_custom_reports', __name__, url_prefix='/server/custom-reports')

NAME_MAX = 120


def _name(raw: Any) -> str:
    name = (raw or '').strip() if isinstance(raw, str) else ''
    if not 1 <= len(name) <= NAME_MAX:
        raise ScopeError(f'name is required (1..{NAME_MAX} characters)', 400)
    return name


_DEFINITION_KEYS = ('filter', 'columns', 'chart', 'sort', 'order', 'include_discarded')


def _stored_definition(row: Dict[str, Any]) -> Dict[str, Any]:
    filter_doc = row.get('filter') if isinstance(row.get('filter'), dict) else {}
    return {
        'filter': {'schema_version': row.get('schema_version'), 'tql': filter_doc.get('tql', '')},
        'columns': row.get('columns') or [],
        'chart': row.get('chart') if isinstance(row.get('chart'), dict) else {'type': 'none'},
        'sort': filter_doc.get('sort'),
        'order': filter_doc.get('order'),
        'include_discarded': filter_doc.get('include_discarded', False),
    }


def _present(row: Dict[str, Any]) -> Dict[str, Any]:
    stored = _stored_definition(row)
    try:
        document = report_query.validate_definition(stored).to_document()
        valid: Dict[str, Any] = {'valid': True}
    except report_query.QueryError as e:
        document = stored
        valid = {'valid': False, 'validation_error': e.to_dict()}
    return {
        'id': row.get('id'),
        'name': row.get('name'),
        'created_by': row.get('created_by'),
        'created_at': row.get('created_at'),
        'updated_at': row.get('updated_at'),
        **document,
        **valid,
    }


def _storage_fields(definition: report_query.ReportDefinition) -> Dict[str, Any]:
    doc = definition.to_document()
    return {
        'schema_version': doc['filter']['schema_version'],
        'filter_doc': {'tql': doc['filter']['tql'], 'sort': doc['sort'], 'order': doc['order'],
                       'include_discarded': doc['include_discarded']},
        'columns': doc['columns'],
        'chart': doc['chart'],
    }


def _validate(raw: Dict[str, Any]) -> report_query.ReportDefinition:
    try:
        return report_query.validate_definition(raw)
    except report_query.QueryError as e:
        raise ScopeError(e.message, 400)


@server_custom_reports_bp.route('', methods=['GET'])
@handle_route_exceptions('custom_reports:list')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def list_reports():
    team_id = resolve_team_id()
    rows = custom_reports_db.list_reports(team_id, actor_id())
    return jsonify({'items': [_present(r) for r in rows]})


@server_custom_reports_bp.route('', methods=['POST'])
@handle_route_exceptions('custom_reports:create')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def create_report():
    team_id = resolve_team_id()
    body = json_body()
    name = _name(body.get('name'))
    fields = _storage_fields(_validate({k: body.get(k) for k in _DEFINITION_KEYS if k in body}))
    row = custom_reports_db.create_report(team_id, actor_id(), name=name, **fields)
    return jsonify(_present(row)), 201


@server_custom_reports_bp.route('/<report_id>', methods=['GET'])
@handle_route_exceptions('custom_reports:get')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def get_report(report_id: str):
    team_id = resolve_team_id()
    row = custom_reports_db.get_report(team_id, actor_id(), require_uuid(report_id, 'report_id'))
    if not row:
        return error_json('report not found', 404)
    return jsonify(_present(row))


@server_custom_reports_bp.route('/<report_id>', methods=['PATCH'])
@handle_route_exceptions('custom_reports:update')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def update_report(report_id: str):
    team_id = resolve_team_id()
    body = json_body()
    unknown = set(body) - {'team_id', 'name', *_DEFINITION_KEYS}
    if unknown:
        return error_json(f'unexpected fields: {", ".join(sorted(unknown))}', 400)
    changes: Dict[str, Any] = {}
    if 'name' in body:
        changes['name'] = _name(body.get('name'))
    if any(k in body for k in _DEFINITION_KEYS):
        existing = custom_reports_db.get_report(team_id, actor_id(), require_uuid(report_id, 'report_id'))
        if not existing:
            return error_json('report not found', 404)
        merged = _stored_definition(existing)
        merged.update({k: body[k] for k in _DEFINITION_KEYS if k in body})
        fields = _storage_fields(_validate(merged))
        changes.update({'schema_version': fields['schema_version'], 'filter': fields['filter_doc'],
                        'columns': fields['columns'], 'chart': fields['chart']})
    if not changes:
        return error_json('nothing to update', 400)
    row = custom_reports_db.update_report(team_id, actor_id(), require_uuid(report_id, 'report_id'), changes)
    if not row:
        return error_json('report not found', 404)
    return jsonify(_present(row))


@server_custom_reports_bp.route('/<report_id>', methods=['DELETE'])
@handle_route_exceptions('custom_reports:delete')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def delete_report(report_id: str):
    team_id = resolve_team_id()
    if not custom_reports_db.delete_report(team_id, actor_id(), require_uuid(report_id, 'report_id')):
        return error_json('report not found', 404)
    return jsonify({'deleted': True, 'id': report_id})
