"""
Verification Routes - Server Logic Only

This module provides verification endpoints that require server-side logic.
Pure proxy routes have been moved to auto_proxy.py.
"""

from flask import Blueprint, request, jsonify
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

# Create blueprint
server_verification_bp = Blueprint('server_verification', __name__, url_prefix='/server/verification')

# =====================================================
# SERVER LOGIC ROUTES (keep these)
# =====================================================

@server_verification_bp.route('/getVerifications', methods=['GET'])
@handle_route_exceptions('verification:get_verifications')
def get_verifications():
    """Get available verifications for a device model (for frontend compatibility)."""
    device_model = request.args.get('device_model', 'android_mobile')
    team_id = request.args.get('team_id')
    
    # Delegate to service layer (business logic moved out of route)
    from services.verification_service import verification_service
    result = verification_service.get_verification_types(device_model)
    
    if result['success']:
        return jsonify({
            'success': True,
            'verifications': result['verifications']
        })
    else:
        return jsonify({
            'success': False,
            'message': result['error']
        }), 500
    
@server_verification_bp.route('/getAllReferences', methods=['POST'])
@handle_route_exceptions('verification:get_all_references')
def get_all_references():
    """Get all reference images/data."""
    team_id = request.args.get('team_id')
    userinterface_name = request.args.get('userinterface_name')  # OPTIMAL: Direct userinterface filter
    device_model = request.args.get('device_model')  # FALLBACK: Device model compatibility filter
    # Editor reload-after-save sets this so the dropdown reflects a write made on
    # the backend_host (which can't invalidate this process's cache).
    bust_cache = request.args.get('bust_cache', '').lower() in ('1', 'true', 'yes')

    # Delegate to service layer
    from services.verification_service import verification_service
    result = verification_service.get_all_references(team_id, userinterface_name, device_model, bust_cache=bust_cache)
    
    if result['success']:
        return jsonify({
            'success': True,
            'references': result['references']
        })
    else:
        status_code = result.get('status_code', 500)
        return jsonify({
            'success': False,
            'message': result['error']
        }), status_code


@server_verification_bp.route('/getReferenceVersions', methods=['POST'])
@handle_route_exceptions('verification:get_reference_versions')
def get_reference_versions_route():
    """List version history (newest first) for a single reference."""
    from shared.src.lib.database.verifications_references_db import get_reference_versions

    team_id = request.args.get('team_id')
    data = request.get_json(silent=True) or {}
    reference_id = data.get('reference_id') or request.args.get('reference_id')
    if not team_id or not reference_id:
        return jsonify({'success': False, 'message': 'team_id and reference_id are required'}), 400

    print(f'[@route:server_verification:get_reference_versions] reference {reference_id}')
    result = get_reference_versions(team_id=team_id, reference_id=reference_id)
    if result['success']:
        return jsonify({'success': True, 'versions': result['versions']})
    return jsonify({'success': False, 'message': result.get('error', 'Failed to get versions')}), 500


@server_verification_bp.route('/restoreReferenceVersion', methods=['POST'])
@handle_route_exceptions('verification:restore_reference_version')
def restore_reference_version_route():
    """Restore a reference to an earlier version (undoable — current state is
    snapshotted first)."""
    from shared.src.lib.database.verifications_references_db import restore_reference_version

    team_id = request.args.get('team_id')
    data = request.get_json(silent=True) or {}
    reference_id = data.get('reference_id')
    version_id = data.get('version_id')
    if not team_id or not reference_id or not version_id:
        return jsonify({'success': False, 'message': 'team_id, reference_id and version_id are required'}), 400

    print(f'[@route:server_verification:restore_reference_version] reference {reference_id} -> version {version_id}')
    result = restore_reference_version(team_id=team_id, reference_id=reference_id, version_id=version_id)
    if result['success']:
        return jsonify(result)
    return jsonify({'success': False, 'message': result.get('error', 'Failed to restore version')}), 500


# =====================================================
# HEALTH CHECK
# =====================================================

@server_verification_bp.route('/health', methods=['GET'])
@handle_route_exceptions('verification:health_check')
def health_check():
    """Health check endpoint for verification execution service"""
    return jsonify({
        'success': True,
        'message': 'Verification execution service is running',
        'note': 'Pure proxy routes moved to auto_proxy.py'
    })
