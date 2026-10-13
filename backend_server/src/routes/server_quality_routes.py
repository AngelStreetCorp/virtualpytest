"""Quality insights: flaky, slow and not-executed-in-window (TASK-42 §4.4).

    GET /server/script-results/flaky?team_id=&window_days=14&limit=100
    GET /server/script-results/slow?team_id=&window_days=30&limit=100
    GET /server/script-results/never-executed?team_id=&window_days=30&limit=200

All three accept the workspace scope (``host_filter`` / ``device_filter`` JSON
arrays) and are limited to this server's registered hosts. Responses always
carry the window, the minimum sample and the sample sizes.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend_server.src.lib.auth_middleware import require_permission, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.services.analytics import quality
from backend_server.src.services.analytics.scope import bounded_int, handle_scope_errors, resolve_scope

server_quality_bp = Blueprint('server_quality', __name__, url_prefix='/server/script-results')


def _window(default_days: int) -> int:
    return bounded_int(request.args.get('window_days'), default=default_days, minimum=1,
                       maximum=quality.MAX_WINDOW_DAYS, name='window_days')


def _limit(default: int) -> int:
    return bounded_int(request.args.get('limit'), default=default, minimum=1, maximum=1000, name='limit')


@server_quality_bp.route('/flaky', methods=['GET'])
@handle_route_exceptions('quality:flaky')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def list_flaky():
    scope = resolve_scope()
    return jsonify(quality.flaky(scope, _window(quality.FLAKY_DEFAULT_WINDOW_DAYS), _limit(100)))


@server_quality_bp.route('/slow', methods=['GET'])
@handle_route_exceptions('quality:slow')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def list_slow():
    scope = resolve_scope()
    return jsonify(quality.slow(scope, _window(quality.SLOW_DEFAULT_WINDOW_DAYS), _limit(100)))


@server_quality_bp.route('/never-executed', methods=['GET'])
@handle_route_exceptions('quality:not_executed')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def list_not_executed():
    scope = resolve_scope()
    return jsonify(quality.not_executed(scope, _window(quality.NOT_EXECUTED_DEFAULT_WINDOW_DAYS), _limit(200)))
