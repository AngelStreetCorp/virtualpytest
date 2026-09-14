"""
Device Flags Routes - Minimal implementation for device clustering/tagging
"""

from flask import Blueprint, request, jsonify

from shared.src.lib.utils.supabase_utils import get_supabase_client
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

device_flags_bp = Blueprint('device_flags', __name__, url_prefix='/server/device-flags')


@device_flags_bp.route('/', methods=['GET'], strict_slashes=False)  # no http:// 308 behind the proxy (BUG-0045)
@handle_route_exceptions('device_flags:get_all')
def get_all_device_flags():
    """Get all device flags"""
    supabase = get_supabase_client()
    result = supabase.table('device_flags').select('*').execute()
    return jsonify({'success': True, 'data': result.data}), 200


@device_flags_bp.route('/<host_name>/<device_id>', methods=['PUT'])
@handle_route_exceptions('device_flags:update')
def update_device_flags(host_name, device_id):
    """Update flags for a specific device"""
    data = request.get_json() or {}
    flags = data.get('flags', [])
    if not isinstance(flags, list):
        return jsonify({'error': 'flags must be an array'}), 400
    supabase = get_supabase_client()
    result = supabase.table('device_flags').update({
        'flags': flags,
        'updated_at': 'now()'
    }).eq('host_name', host_name).eq('device_id', device_id).execute()
    if not result.data:
        return jsonify({'error': 'Device not found'}), 404
    return jsonify({'success': True, 'data': result.data[0]}), 200


@device_flags_bp.route('/batch', methods=['GET'])
@handle_route_exceptions('device_flags:batch')
def get_batch_device_flags():
    """Get both device flags and unique flags in one request"""
    supabase = get_supabase_client()
    device_flags_result = supabase.table('device_flags').select('*').execute()
    device_flags = device_flags_result.data
    unique_flags = set()
    for row in device_flags:
        flags = row.get('flags', [])
        if flags:
            unique_flags.update(flags)
    return jsonify({
        'success': True,
        'data': {'device_flags': device_flags, 'unique_flags': sorted(list(unique_flags))}
    }), 200


@device_flags_bp.route('/flags', methods=['GET'])
@handle_route_exceptions('device_flags:flags')
def get_unique_flags():
    """Get all unique flags across all devices"""
    supabase = get_supabase_client()
    result = supabase.table('device_flags').select('flags').execute()
    unique_flags = set()
    for row in result.data:
        flags = row.get('flags', [])
        if flags:
            unique_flags.update(flags)
    return jsonify({'success': True, 'data': sorted(list(unique_flags))}), 200


def upsert_device_on_registration(host_name: str, device_id: str, device_name: str):
    """Ensure device exists in flags table during registration.

    Must NEVER overwrite an existing row: hosts re-register on every service
    restart, and a blind upsert with flags=[] wipes user-set tags."""
    supabase = get_supabase_client()
    existing = supabase.table('device_flags').select('device_name') \
        .eq('host_name', host_name).eq('device_id', device_id).execute()
    if existing.data:
        if existing.data[0].get('device_name') != device_name:
            supabase.table('device_flags').update({
                'device_name': device_name,
                'updated_at': 'now()'
            }).eq('host_name', host_name).eq('device_id', device_id).execute()
        return
    supabase.table('device_flags').upsert({
        'host_name': host_name,
        'device_id': device_id,
        'device_name': device_name,
        'flags': []
    }, on_conflict='host_name,device_id', ignore_duplicates=True).execute()
    print(f"✅ [device_flags] Auto-registered device: {host_name}/{device_id}")