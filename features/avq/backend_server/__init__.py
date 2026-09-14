"""
AVQ feature - backend_server part.

Registered by shared/src/lib/utils/features.py when the feature is enabled
(see docs/technical/FEATURES.md). Routes live under /server/monitoring like the
core monitoring routes; static rules win over auto_proxy's /server/<path>.
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request, jsonify

from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

feature_avq_bp = Blueprint('feature_avq', __name__, url_prefix='/server/monitoring')


@feature_avq_bp.route('/avq', methods=['GET'])
@handle_route_exceptions('monitoring:get_avq_metrics')
def get_avq_metrics():
    """Per-minute Audio/Video Quality (AVQ) rows for one device over a window.

    Query params: device_id (required), host_name, hours (default 24).
    Returns: { success, count, metrics: [...] } ordered by timestamp asc.
    """
    from features.avq.lib.quality_metrics_db import get_quality_metrics

    device_id = request.args.get('device_id')
    if not device_id:
        return jsonify({'success': False, 'error': 'device_id is required'}), 400
    host_name = request.args.get('host_name')  # device_id is NOT unique across hosts

    try:
        hours = float(request.args.get('hours', 24))
    except ValueError:
        hours = 24
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    rows = get_quality_metrics(device_id, since, host_name=host_name)
    return jsonify({'success': True, 'count': len(rows), 'metrics': rows})


@feature_avq_bp.route('/zaps', methods=['GET'])
@handle_route_exceptions('monitoring:get_avq_zaps')
def get_avq_zaps():
    """Zap events for one device over a window (AVQ timeline ZAPS lane).

    Query params: device_name (required), host_name, hours (default 24), team_id.
    """
    from shared.src.lib.database.zap_results_db import get_zap_results

    team_id = request.args.get('team_id')
    device_name = request.args.get('device_name')
    host_name = request.args.get('host_name')
    if not team_id or not device_name:
        return jsonify({'success': False, 'error': 'team_id and device_name are required'}), 400
    try:
        hours = float(request.args.get('hours', 24))
    except ValueError:
        hours = 24
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    res = get_zap_results(team_id, host_name=host_name, device_name=device_name, limit=300)
    rows = res.get('zap_results', []) if res.get('success') else []
    # keep only zaps within the window (get_zap_results has no time filter)
    out = [z for z in rows if (z.get('execution_date') or '') >= since.isoformat()]
    return jsonify({'success': True, 'count': len(out), 'zaps': out})


def register(app):
    app.register_blueprint(feature_avq_bp)
