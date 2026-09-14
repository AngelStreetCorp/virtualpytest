"""
Device Info Overrides Routes

Admin curation of OCR-extracted device info. Lets an operator correct the
*value* of any field (keys are dynamic per UI) for a given device. Corrections
are stored per-device, per-key and applied non-destructively at read time by the
device_info_corrected / device_info_key_status views (raw OCR is never mutated).

All endpoints use the platform-default `require_user_auth_if_enabled` —
JWT-gated when the deployment enforces frontend auth (ENFORCE_FRONTEND_JWT +
SUPABASE_JWT_SECRET), pass-through otherwise. Correcting device info is a
per-device operational task (reached from the device-control page), not
platform admin config, so writes are not admin-gated.
"""
from flask import Blueprint, request, jsonify
import logging

from shared.src.lib.database import device_info_overrides_db
from shared.src.lib.utils.app_utils import get_team_id, check_supabase
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.auth_middleware import require_user_auth_if_enabled

logger = logging.getLogger(__name__)

server_device_info_overrides_bp = Blueprint(
    'server_device_info_overrides', __name__, url_prefix='/server/device-info-overrides'
)

# Which info family a request targets. 'device' = OCR device info (default),
# 'gateway' = gw_info gateway info. Same table/routes serve both (info_source col).
_VALID_SOURCES = ('device', 'gateway')


def _source(value) -> str:
    return value if value in _VALID_SOURCES else 'device'


@server_device_info_overrides_bp.route('/keys', methods=['GET'])
@require_user_auth_if_enabled
@handle_route_exceptions('device_info_overrides:get_keys')
def get_keys():
    """Per-key correction status for the latest scan of a device.

    Query params: device_name (optional), host_name (optional). Without a
    device, returns the full status set for the team.
    """
    error = check_supabase()
    if error:
        return error
    team_id = request.args.get('team_id') or get_team_id()
    device_name = request.args.get('device_name')
    host_name = request.args.get('host_name')
    info_source = _source(request.args.get('source'))
    rows = device_info_overrides_db.get_key_status(team_id, device_name, host_name, info_source)
    return jsonify(rows), 200


@server_device_info_overrides_bp.route('', methods=['PUT'])
@require_user_auth_if_enabled
@handle_route_exceptions('device_info_overrides:upsert')
def upsert_override():
    """Create or update a per-key value correction."""
    error = check_supabase()
    if error:
        return error
    data = request.get_json() or {}
    required = ['device_name', 'host_name', 'info_key', 'corrected_value']
    missing = [k for k in required if not data.get(k) and data.get(k) != '']
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    team_id = data.get('team_id') or get_team_id()
    result = device_info_overrides_db.upsert_override(
        team_id=team_id,
        device_name=data['device_name'],
        host_name=data['host_name'],
        userinterface_name=data.get('userinterface_name'),
        info_key=data['info_key'],
        corrected_value=data['corrected_value'],
        raw_value_at_edit=data.get('raw_value_at_edit'),
        note=data.get('note'),
        updated_by=getattr(request, 'user_email', None),
        info_source=_source(data.get('source')),
    )
    if not result:
        return jsonify({"error": "Failed to save override"}), 500
    return jsonify(result), 200


@server_device_info_overrides_bp.route('', methods=['DELETE'])
@require_user_auth_if_enabled
@handle_route_exceptions('device_info_overrides:delete')
def delete_override():
    """Remove a per-key override; views fall back to raw OCR."""
    error = check_supabase()
    if error:
        return error
    data = request.get_json() or {}
    required = ['device_name', 'host_name', 'info_key']
    missing = [k for k in required if not data.get(k)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    team_id = data.get('team_id') or get_team_id()
    success = device_info_overrides_db.delete_override(
        team_id=team_id,
        device_name=data['device_name'],
        host_name=data['host_name'],
        userinterface_name=data.get('userinterface_name'),
        info_key=data['info_key'],
        info_source=_source(data.get('source')),
    )
    if not success:
        return jsonify({"error": "Override not found"}), 404
    return jsonify({"message": "Override removed"}), 200
