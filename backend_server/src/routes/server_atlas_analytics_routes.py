"""Server-to-server half of Atlas analytics (TASK-43).

A backend server without a direct read-only database connection forwards the database
part of an analytics request here (``RemoteAnalytics`` in
``backend_server/src/lib/analytics/service.py``). The body carries the caller's trusted
Atlas context, so these routes accept **only** the shared service key — never a user
token or the auto-sign token — and re-check the team against the named user's
memberships before running the same guarded, read-only query.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend_server.src.lib.analytics.service import AnalyticsContext, AnalyticsService, AnalyticsValidationError
from backend_server.src.lib.auth_middleware import (
    SHARED_PRINCIPAL_USER_IDS, _is_valid_service_api_key, _team_ids_from_db,
)

server_atlas_analytics_bp = Blueprint('server_atlas_analytics', __name__, url_prefix='/server/atlas-analytics')


def _trusted_context():
    """The forwarded context, or an error response when the caller may not send one."""
    if not _is_valid_service_api_key():
        return None, (jsonify({'error': 'service key required'}), 403)
    body = request.get_json(silent=True) or {}
    context = AnalyticsContext.from_dict(body.get('context') or {})
    if not context.team_id:
        return None, (jsonify({'error': 'Authenticated team context is required'}), 400)
    # A person's team is re-checked; a shared principal (auto-sign, service key, open mode)
    # has no membership rows, and the forwarding socket handler already skipped it too.
    if (context.user_id and context.user_id not in SHARED_PRINCIPAL_USER_IDS
            and context.team_id not in _team_ids_from_db(context.user_id)):
        return None, (jsonify({'error': 'Team scope is not authorized'}), 403)
    return context, None


def _service() -> AnalyticsService:
    service = AnalyticsService()
    if not service.dsn:
        # This server would only forward again; refuse instead of looping between servers.
        raise AnalyticsValidationError('Analytics datasource is not configured on this server')
    return service


@server_atlas_analytics_bp.route('/query', methods=['POST'])
def forwarded_query():
    context, error = _trusted_context()
    if error:
        return error
    analytics_request = (request.get_json(silent=True) or {}).get('request') or {}
    try:
        return jsonify({'result': _service().query(analytics_request, context)})
    except AnalyticsValidationError as exc:
        return jsonify({'error': str(exc)}), 400


@server_atlas_analytics_bp.route('/device-scope', methods=['POST'])
def forwarded_device_scope():
    context, error = _trusted_context()
    if error:
        return error
    try:
        return jsonify({'result': sorted(_service().allowed_device_keys(context))})
    except AnalyticsValidationError as exc:
        return jsonify({'error': str(exc)}), 400


@server_atlas_analytics_bp.route('/grafana-draft', methods=['POST'])
def forwarded_grafana_draft():
    """Create + push a Grafana draft for a server that has no Grafana credentials (service key only)."""
    context, error = _trusted_context()
    if error:
        return error
    from backend_server.src.lib.analytics.grafana_push import GrafanaDraftPublisher, GrafanaPushError
    analytics_request = (request.get_json(silent=True) or {}).get('request') or {}
    try:
        # forward=False: this server never forwards again, so two servers cannot loop.
        publisher = GrafanaDraftPublisher(AnalyticsService(), forward=False)
        return jsonify({'result': publisher.publish(analytics_request, context)})
    except (AnalyticsValidationError, GrafanaPushError) as exc:
        # 400 so the calling server surfaces this message, not a bare HTTP error.
        return jsonify({'error': str(exc)}), 400
