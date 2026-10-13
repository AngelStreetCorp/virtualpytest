"""Live run status and stop (TASK-42 §4.3 Live).

    GET  /server/run-management/live/<task_id>?team_id=[&host_filter=][&device_filter=]
    POST /server/run-management/live/<task_id>/stop     {team_id}

Adapts the existing script task records (see ``services/live/adapter.py``);
the browser polls this server (every 2 s while visible) and never calls a
host. A task of another team, or on a host/device outside the caller's scope,
answers exactly like a missing one: 404 with ``status: unknown``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from backend_server.src.lib.auth_middleware import (
    principal_holds_permission,
    require_permission,
    require_user_auth,
)
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.server_utils import get_host_manager
from backend_server.src.lib.utils.task_manager import task_manager
from backend_server.src.services.analytics.scope import (
    actor_id,
    handle_scope_errors,
    registered_hosts,
    resolve_scope,
)
from backend_server.src.services.live import adapter
from shared.src.lib.utils.build_url_utils import call_host

server_live_bp = Blueprint('server_run_management_live', __name__, url_prefix='/server/run-management/live')


def _not_found(task_id: str):
    return jsonify({**adapter.unknown(task_id), 'error': 'task not found'}), 404


@server_live_bp.route('/<task_id>', methods=['GET'])
@handle_route_exceptions('live:status')
@require_user_auth
@require_permission('reports.tests:view')
@handle_scope_errors
def live_status(task_id: str):
    hosts = registered_hosts()
    scope = resolve_scope(hosts=hosts)
    task = task_manager.get_task(task_id)
    if not adapter.visible_task(task, scope, hosts):
        return _not_found(task_id)
    response = jsonify(adapter.snapshot(task_id, task, scope, hosts=hosts,
                                        can_stop_permission=principal_holds_permission(adapter.STOP_PERMISSION)))
    response.headers['Cache-Control'] = 'no-store'
    return response


@server_live_bp.route('/<task_id>/stop', methods=['POST'])
@handle_route_exceptions('live:stop')
@require_user_auth
@require_permission(adapter.STOP_PERMISSION)
@handle_scope_errors
def stop_task(task_id: str):
    hosts = registered_hosts()
    scope = resolve_scope(hosts=hosts)
    task = task_manager.get_task(task_id)
    if not adapter.visible_task(task, scope, hosts):
        return _not_found(task_id)
    if adapter.map_status(task) != 'running':
        return jsonify({'success': False, 'status': adapter.map_status(task),
                        'error': 'task is not running'}), 409
    host_info = get_host_manager().get_host((task.get('params') or {}).get('host_name'))
    if not host_info:
        return jsonify({'success': False, 'status': 'unknown',
                        'error': 'host is no longer registered on this server'}), 409
    outcome = adapter.request_stop(task_id, task, host_info, actor_id(), task_manager, call_host)
    return jsonify(outcome['body']), outcome['http']
