"""
Alerts Management Routes

This module contains the alerts management API endpoints for:
- Active alerts retrieval
- Closed alerts retrieval
- Alert filtering
"""

import logging

from flask import Blueprint, jsonify, request

from shared.src.lib.database.alerts_db import (
    get_alert_by_id,
    get_all_alerts,
    get_active_alerts,
    get_closed_alerts,
    update_alert_checked_status,
    update_alert_discard_status,
    delete_all_alerts,
    delete_alert
)
from shared.src.lib.utils.app_utils import check_supabase
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_alerts_bp = Blueprint('server_alerts', __name__, url_prefix='/server/alerts')

logger = logging.getLogger(__name__)


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
    profile = request.args.get('profile')  # optional monitor profile filter (TASK-90)
    active_limit = int(request.args.get('active_limit', 100))
    resolved_limit = int(request.args.get('resolved_limit', 100))

    result = get_all_alerts(
        host_name=host_name,
        device_id=device_id,
        incident_type=incident_type,
        active_limit=active_limit,
        resolved_limit=resolved_limit,
        profile=profile
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
    if not success:
        return jsonify({'error': 'Alert not found or failed to update'}), 404
    team_id = request.args.get('team_id')
    # A person's Discard or Keep (check_type manual) needs the alert once: its metadata.screen_id teaches the screen
    # memory either way (Discard -> expected, Keep -> bad: BUG-0746, Discard had stopped teaching), and a Keep labels
    # the training samples with its incident_type. Both helpers take the pre-fetched row, so one lookup per click.
    alert = get_alert_by_id(alert_id) if check_type == 'manual' else None
    _label_alert_training_samples(alert_id, discard, check_type, team_id, alert)
    _teach_screen_memory(alert_id, discard, check_type, alert)
    return jsonify({'status': 'success'})


@server_alerts_bp.route('/triageStats', methods=['GET'])
@handle_route_exceptions('server_alerts:triageStats')
def triage_stats_route():
    """Today's alert-triage calls, failures, tokens, discards by screen memory and known screens."""
    err = check_supabase()
    if err:
        return err
    from shared.src.lib.database.alerts_db import get_triage_stats
    stats = get_triage_stats()
    return jsonify(stats), (200 if stats.get('success') else 500)


def _teach_screen_memory(alert_id, discard, check_type, alert=None):
    """TASK-84: a person's Discard/Keep on an alert the host stamped with a screen id becomes that screen's
    verdict (expected / bad), source human. Best effort, never raises, never changes the route's response.

    ``alert`` is the pre-fetched alert row the route already has; when it is None (direct
    callers, tests) we fall back to looking the row up ourselves so the helper stays
    usable from outside the route.
    """
    try:
        if check_type != 'manual':
            return
        if alert is None:
            alert = get_alert_by_id(alert_id)
        if not alert:
            return
        screen_id = ((alert.get('metadata') or {})).get('screen_id')
        if screen_id:
            from shared.src.lib.database import screen_fingerprints_db
            screen_fingerprints_db.set_human_verdict(screen_id, bool(discard), alert_id)
    except Exception as e:
        logger.warning(f"[screen-memory] teaching from alert {alert_id} failed: {e}")


def _label_alert_training_samples(alert_id, discard, check_type, team_id, alert=None):
    """TASK-27 step 3a: turn a human discard/confirm into the label of the alert's
    ``av-fault`` training samples (recorded by the host at alert creation).

    discard=true: the detector was wrong, ``incident_type`` None. discard=false with a
    manual check: confirmed, the alert's own type. Best effort, never raises, and never
    changes the route's response.

    ``alert`` is the pre-fetched alert row the route already has; for the discard branch
    we never need it, and for the confirm branch we don't re-look it up if the row is
    passed in. Direct callers (and the tests) that omit it keep working via the
    fallback get_alert_by_id().
    """
    try:
        if not team_id or not (discard or check_type == 'manual'):
            return
        from shared.src.lib.ai import training_samples
        from shared.src.lib.database import ai_training_samples_db as samples_db
        if not training_samples.enabled():
            return
        samples = samples_db.get_samples_by_source_ref(team_id, 'alert_id', alert_id)
        if not samples:
            return
        if discard:
            ground_truth = {'incident_type': None}
        else:
            if alert is None:
                alert = get_alert_by_id(alert_id)
            if not alert or not alert.get('incident_type'):
                logger.warning(f"[training] alert {alert_id} not found, samples left unlabelled")
                return
            ground_truth = {'incident_type': alert['incident_type']}
        for sample in samples:
            training_samples.attach_ground_truth(sample['id'], team_id, ground_truth, 'human')
    except Exception as e:
        logger.warning(f"[training] labelling samples of alert {alert_id} failed: {e}")


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


@server_alerts_bp.route('/deleteAlert/<alert_id>', methods=['DELETE'])
@handle_route_exceptions('server_alerts:deleteAlert')
def delete_alert_route(alert_id):
    """Delete a single alert"""
    err = check_supabase()
    if err:
        return err
    result = delete_alert(alert_id)
    if result['success']:
        return jsonify({'success': True, 'deleted_count': result['deleted_count']})
    status = 404 if result['error'] == 'Alert not found' else 500
    return jsonify({'success': False, 'error': result['error']}), status
