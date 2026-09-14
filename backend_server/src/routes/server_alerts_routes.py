"""
Alerts Management Routes

This module contains the alerts management API endpoints for:
- Active alerts retrieval
- Closed alerts retrieval
- Alert filtering
"""

from flask import Blueprint, jsonify, request

from shared.src.lib.database.alerts_db import (
    get_all_alerts,
    get_active_alerts,
    get_closed_alerts,
    update_alert_checked_status,
    update_alert_discard_status,
    delete_all_alerts
)
from shared.src.lib.utils.app_utils import check_supabase
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_alerts_bp = Blueprint('server_alerts', __name__, url_prefix='/server/alerts')


def _alerts_error_payload(e):
    return {'success': False, 'error': str(e), 'alerts': [], 'count': 0, 'active_count': 0, 'resolved_count': 0}


def _active_error_payload(e):
    return {'success': False, 'error': str(e), 'alerts': [], 'count': 0}


@server_alerts_bp.route('/getAllAlerts', methods=['GET'])
@handle_route_exceptions('server_alerts:getAllAlerts')
def get_all_alerts_endpoint():
    """Get all alerts (both active and resolved) - optimized split queries."""
    host_name = request.args.get('host_name')
    device_id = request.args.get('device_id')
    incident_type = request.args.get('incident_type')
    active_limit = int(request.args.get('active_limit', 100))
    resolved_limit = int(request.args.get('resolved_limit', 100))

    result = get_all_alerts(
        host_name=host_name,
        device_id=device_id,
        incident_type=incident_type,
        active_limit=active_limit,
        resolved_limit=resolved_limit
    )

    if result['success']:
        return jsonify({
            'success': True,
            'alerts': result['alerts'],
            'count': result['count'],
            'active_count': result['active_count'],
            'resolved_count': result['resolved_count']
        })
    return jsonify(_alerts_error_payload(result.get('error'))), 500


@server_alerts_bp.route('/getActiveAlerts', methods=['GET'])
@handle_route_exceptions('server_alerts:getActiveAlerts')
def get_all_active_alerts():
    """Get all active alerts."""
    result = get_active_alerts()
    if result['success']:
        return jsonify({'success': True, 'alerts': result['alerts'], 'count': result['count']})
    return jsonify(_active_error_payload(result.get('error'))), 500


@server_alerts_bp.route('/getClosedAlerts', methods=['GET'])
@handle_route_exceptions('server_alerts:getClosedAlerts')
def get_all_closed_alerts():
    """Get all closed/resolved alerts."""
    result = get_closed_alerts()
    if result['success']:
        return jsonify({'success': True, 'alerts': result['alerts'], 'count': result['count']})
    return jsonify(_active_error_payload(result.get('error'))), 500


@server_alerts_bp.route('/updateCheckedStatus/<alert_id>', methods=['PUT'])
@handle_route_exceptions('server_alerts:updateCheckedStatus')
def update_alert_checked_status_route(alert_id):
    """Update alert checked status"""
    err = check_supabase()
    if err:
        return err
    data = request.json or {}
    checked = data.get('checked', False)
    check_type = data.get('check_type', 'manual')
    success = update_alert_checked_status(alert_id, checked, check_type)
    if success:
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Alert not found or failed to update'}), 404


@server_alerts_bp.route('/updateDiscardStatus/<alert_id>', methods=['PUT'])
@handle_route_exceptions('server_alerts:updateDiscardStatus')
def update_alert_discard_status_route(alert_id):
    """Update alert discard status"""
    err = check_supabase()
    if err:
        return err
    data = request.json or {}
    discard = data.get('discard', False)
    discard_comment = data.get('discard_comment')
    check_type = data.get('check_type', 'manual')
    success = update_alert_discard_status(alert_id, discard, discard_comment, check_type)
    if success:
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Alert not found or failed to update'}), 404


@server_alerts_bp.route('/deleteAllAlerts', methods=['DELETE'])
@handle_route_exceptions('server_alerts:deleteAllAlerts')
def delete_all_alerts_route():
    """Delete all alerts from the database"""
    err = check_supabase()
    if err:
        return err
    result = delete_all_alerts()
    if result['success']:
        return jsonify({
            'success': True,
            'deleted_count': result['deleted_count'],
            'message': result['message']
        })
    return jsonify({'success': False, 'error': result['error'], 'deleted_count': 0}), 500
