"""TQL validation and the report query endpoint (TASK-42 §4.4).

    GET  /server/tql?q=<TQL>                      parse + validate only
    POST /server/run-management/query             execute a report definition
    POST /server/run-management/query/export      same definition, CSV (up to
                                                  EXPORT_ROW_CAP rows, paged;
                                                  X-Total-Count / X-Row-Cap /
                                                  X-Truncated describe the cut)

The query endpoints take the report definition documented in
``services/analytics/report_query.py`` plus ``team_id``, optional workspace
scope (``host_filter`` / ``device_filter``) and ``limit`` / ``offset``. Filters
are validated and executed server-side before counting, charting and paging.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics import report_query, tql
from backend_server.src.services.analytics.scope import (
    bounded_int,
    handle_scope_errors,
    json_body,
    resolve_scope,
)
from backend_server.src.services.sharing.csv_export import build_csv

server_tql_bp = Blueprint('server_tql', __name__)


@server_tql_bp.route('/server/tql', methods=['GET'])
@handle_route_exceptions('tql:validate')
@require_user_auth
@require_permission('reports.tests:view')
def validate_tql():
    query = request.args.get('q', '')
    try:
        parsed = tql.parse(query)
    except tql.TqlError as e:
        return jsonify({'ok': False, 'error': e.message, 'position': e.position}), 400
    return jsonify({
        'ok': True,
        'clauses': [{'key': c.key, 'value': c.value, 'start': c.start, 'end': c.end} for c in parsed.clauses],
        'filter': parsed.to_dict(),
    })


def _definition_or_error():
    try:
        return report_query.validate_definition(json_body()), None
    except report_query.QueryError as e:
        return None, (jsonify(e.to_dict()), 400)


@server_tql_bp.route('/server/run-management/query', methods=['POST'])
@handle_route_exceptions('tql:query')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def run_query():
    body = json_body()
    scope = resolve_scope()
    definition, error = _definition_or_error()
    if error:
        return error
    limit = bounded_int(body.get('limit'), default=50, minimum=1,
                        maximum=report_query.MAX_PAGE_SIZE, name='limit')
    offset = bounded_int(body.get('offset'), default=0, minimum=0, maximum=1_000_000, name='offset')
    try:
        return jsonify(report_query.execute(scope, definition, limit=limit, offset=offset))
    except report_query.QueryError as e:
        return jsonify(e.to_dict()), 400


@server_tql_bp.route('/server/run-management/query/export', methods=['POST'])
@handle_route_exceptions('tql:query_export')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def export_query():
    scope = resolve_scope()
    definition, error = _definition_or_error()
    if error:
        return error
    try:
        result = report_query.export_rows(scope, definition)
    except report_query.QueryError as e:
        return jsonify(e.to_dict()), 400
    columns = result['columns']
    csv_text = build_csv(columns, [[row.get(c) for c in columns] for row in result['rows']])
    truncated = result['total'] > len(result['rows'])
    return Response(csv_text, mimetype='text/csv; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="run-report.csv"',
        'Cache-Control': 'no-store',
        'X-Total-Count': str(result['total']),
        'X-Row-Cap': str(report_query.EXPORT_ROW_CAP),
        'X-Truncated': 'true' if truncated else 'false',
    })
